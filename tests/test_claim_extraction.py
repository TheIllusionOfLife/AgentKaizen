"""Tests for Feature 2: Claim Extraction for Session Scoring."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentkaizen.session_scoring import (
    build_judge_prompt,
    format_score_summary,
    merge_interactive_scores,
    parse_judge_response,
)


# --- Evidence slice tests ---


def test_build_evidence_slices():
    """Correct truncation and turn extraction from trace messages."""
    from agentkaizen.session_scoring import _build_evidence_slices

    trace = {
        "messages": [
            {"role": "user", "content": "Create a feature branch"},
            {"role": "assistant", "content": "I'll create a branch now." + "x" * 300},
            {"role": "user", "content": "That looks wrong, fix it"},
        ],
        "tool_calls": [
            {
                "name": "bash",
                "arguments": "git checkout -b feat/test",
                "output": "Switched to branch",
            },
            {
                "name": "read",
                "arguments": "/path/to/file.py",
                "output": "file contents" * 50,
            },
        ],
    }

    slices = _build_evidence_slices(trace)
    assert isinstance(slices, list)
    assert len(slices) > 0
    # Each slice should have turn, role, summary
    for s in slices:
        assert "turn" in s
        assert "role" in s
        assert "summary" in s
        # Summaries should be truncated to max_summary_len=200 + "..." = 203
        assert len(s["summary"]) <= 203


def test_build_evidence_slices_empty_trace():
    """Graceful handling of empty messages/tool_calls."""
    from agentkaizen.session_scoring import _build_evidence_slices

    slices = _build_evidence_slices({})
    assert slices == []

    slices = _build_evidence_slices({"messages": [], "tool_calls": []})
    assert slices == []


def test_build_evidence_slices_max_20():
    """Evidence slices capped at 20 entries."""
    from agentkaizen.session_scoring import _build_evidence_slices

    trace = {
        "messages": [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
            for i in range(50)
        ],
        "tool_calls": [
            {"name": f"tool_{i}", "arguments": f"arg_{i}", "output": f"out_{i}"}
            for i in range(10)
        ],
    }

    slices = _build_evidence_slices(trace)
    assert len(slices) <= 20


# --- Judge prompt includes evidence ---


def test_judge_prompt_includes_evidence():
    """Verify evidence_slices in prompt payload when trace has messages."""
    trace = {
        "user_task": "Build a REST API",
        "analysis_summary": "Agent created code",
        "messages": [
            {"role": "user", "content": "Build a REST API"},
            {"role": "assistant", "content": "I'll implement the API"},
        ],
        "tool_calls": [
            {"name": "bash", "arguments": "python app.py", "output": "Server started"},
        ],
    }

    prompt = build_judge_prompt(trace)
    assert "evidence_slices" in prompt
    assert "Build a REST API" in prompt
    assert "claims" in prompt.lower()


def test_judge_prompt_backward_compat_no_messages():
    """When trace has no messages, prompt still works without evidence."""
    trace = {
        "user_task": "Simple task",
        "analysis_summary": "Agent did stuff",
    }

    prompt = build_judge_prompt(trace)
    assert "Simple task" in prompt
    # Should still be valid (no crash)


# --- ClaimResult dataclass ---


def test_claim_result_dataclass():
    """Construction and serialization of ClaimResult."""
    from agentkaizen.session_scoring import ClaimResult

    claim = ClaimResult(
        type="process",
        claim="Agent created feature branch before changes",
        evidence="Turn 3: git checkout -b feat/...",
        pass_=True,
        severity="high",
    )
    assert claim.type == "process"
    assert claim.pass_ is True
    assert claim.severity == "high"

    # Serialization to dict
    d = claim.to_dict()
    assert d["type"] == "process"
    assert d["pass"] is True  # Note: 'pass_' → 'pass' in dict


# --- parse_judge_response claims extraction ---


def test_parse_judge_claims():
    """Valid claims array extraction from judge response."""
    payload = {
        "task_success": 0.8,
        "user_friction": 0.1,
        "workflow_compliance": 0.9,
        "efficiency": 0.7,
        "optimization_relevance": "agents",
        "reasoning": "Good session",
        "claims": [
            {
                "type": "process",
                "claim": "Branch created",
                "evidence": "Turn 3: git checkout -b",
                "pass": True,
                "severity": "high",
            },
            {
                "type": "behavioral",
                "claim": "Ran tests",
                "evidence": "Turn 5: pytest",
                "pass": True,
                "severity": "medium",
            },
        ],
    }

    result = parse_judge_response(json.dumps(payload))
    assert "claims" in result
    assert len(result["claims"]) == 2
    assert result["claims"][0]["type"] == "process"
    assert result["claims"][0]["pass"] is True


def test_parse_judge_claims_missing():
    """Graceful fallback when judge omits claims."""
    payload = {
        "task_success": 0.8,
        "user_friction": 0.1,
        "workflow_compliance": 0.9,
        "efficiency": 0.7,
        "optimization_relevance": "agents",
        "reasoning": "Good session",
    }

    result = parse_judge_response(json.dumps(payload))
    assert "claims" in result
    assert result["claims"] == []


def test_parse_judge_claims_malformed():
    """Malformed claims degrade gracefully to empty list."""
    payload = {
        "task_success": 0.8,
        "user_friction": 0.1,
        "workflow_compliance": 0.9,
        "efficiency": 0.7,
        "optimization_relevance": "agents",
        "reasoning": "Good session",
        "claims": "not a list",
    }

    result = parse_judge_response(json.dumps(payload))
    assert result["claims"] == []


# --- merge_interactive_scores with claims ---


def test_merge_scores_with_claims():
    """Claims propagate through merge_interactive_scores."""
    heuristic_scores = {
        "task_completed": True,
        "task_success_estimate": 0.8,
        "workflow_compliance": 0.9,
        "user_friction": 0.1,
        "efficiency": 0.7,
        "task_context": "code_change",
    }
    judge_scores = {
        "task_success": 0.9,
        "user_friction": 0.05,
        "workflow_compliance": 0.95,
        "efficiency": 0.8,
        "optimization_relevance": "agents",
        "reasoning": "Great",
        "claims": [
            {
                "type": "process",
                "claim": "Branch created",
                "evidence": "Turn 3",
                "pass": True,
                "severity": "high",
            }
        ],
    }

    result = merge_interactive_scores(
        heuristic_scores=heuristic_scores, judge_scores=judge_scores
    )
    assert "claims" in result
    assert len(result["claims"]) == 1


# --- format_score_summary with claims ---


def test_format_summary_with_claims():
    """Verify additive rendering: existing lines preserved + new claims section."""
    result = {
        "derived_user_task": "Build feature X",
        "task_success": 0.8,
        "friction_signals": [],
        "suspicious_signals": [],
        "workflow_failures": [],
        "recommended_changes": [],
        "reasoning": "Good session",
        "heuristics": {
            "workflow_compliance": 0.9,
            "user_friction": 0.1,
            "efficiency": 0.7,
        },
        "claims": [
            {
                "type": "process",
                "claim": "Agent created feature branch",
                "evidence": "Turn 3: git checkout -b feat/...",
                "pass": True,
                "severity": "high",
            },
            {
                "type": "process",
                "claim": "Agent ran tests",
                "evidence": "No test execution found",
                "pass": False,
                "severity": "high",
            },
            {
                "type": "behavioral",
                "claim": "Asked unnecessary questions",
                "evidence": "Turns 5, 8",
                "pass": False,
                "severity": "medium",
            },
        ],
    }

    summary = format_score_summary(result)
    # Existing lines preserved
    assert "Task: Build feature X" in summary
    assert "Outcome:" in summary
    # Claims section added
    assert "Evidence-Based Claims:" in summary
    assert "Process:" in summary
    assert "Behavioral:" in summary


def test_format_summary_without_claims():
    """Existing output unchanged when no claims present."""
    result = {
        "derived_user_task": "Simple task",
        "task_success": 0.5,
        "friction_signals": ["user_corrections"],
        "suspicious_signals": [],
        "workflow_failures": ["missing_branch"],
        "recommended_changes": [],
        "reasoning": "ok",
        "heuristics": {},
    }

    summary = format_score_summary(result)
    assert "Task: Simple task" in summary
    assert "Evidence-Based Claims:" not in summary


# --- Heuristic pseudo-claims ---


def test_heuristic_pseudo_claims():
    """Signal detection → pseudo-claim conversion for heuristic path."""
    from agentkaizen.session_scoring import _synthesize_pseudo_claims

    heuristic_scores = {
        "task_completed": True,
        "workflow_compliance": 0.67,
        "workflow_signal_breakdown": {
            "branch_created": True,
            "used_uv": False,
            "ran_tests": False,
            "ran_lint": None,
            "ran_format": None,
        },
        "user_friction": 0.25,
        "friction_breakdown": {
            "clarification": 0.0,
            "correction": 0.25,
            "execution": 0.0,
        },
        "task_context": "code_change",
    }

    claims = _synthesize_pseudo_claims(heuristic_scores)
    assert isinstance(claims, list)
    assert len(claims) > 0
    # Should have at least one passing and one failing claim
    types_seen = {c["type"] for c in claims}
    assert "process" in types_seen
    pass_values = {c["pass"] for c in claims}
    assert True in pass_values
    assert False in pass_values


def test_subagent_analysis_includes_claims():
    """run_subagent_analysis (default path) wires pseudo-claims into output."""
    from agentkaizen.session_scoring import run_subagent_analysis

    trace_payload = {
        "analysis": {
            "branch_created": True,
            "used_uv": False,
            "ran_tests": False,
            "user_correction_count": 0,
            "clarification_question_count": 0,
            "tool_call_count": 3,
            "error_count": 0,
        },
        "task_context": "code_change",
        "user_task": "Implement feature",
    }

    result = run_subagent_analysis(trace_payload)
    assert "claims" in result
    assert isinstance(result["claims"], list)
