import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_interactive_scoring


def test_score_interactive_heuristics_flags_success_and_workflow():
    trace = {
        "session_id": "s1",
        "thread_name": "demo",
        "analysis": {
            "task_completed": True,
            "branch_created": True,
            "used_uv": True,
            "ran_tests": True,
            "tool_call_count": 3,
            "user_correction_count": 0,
            "clarification_question_count": 0,
        },
    }

    result = codex_interactive_scoring.score_interactive_heuristics(trace)

    assert result["task_completed"] is True
    assert result["workflow_compliance"] == 1.0
    assert result["user_friction"] == 0.0


def test_parse_judge_response_requires_json_object():
    payload = codex_interactive_scoring.parse_judge_response(
        json.dumps(
            {
                "task_success": 0.8,
                "user_friction": 0.1,
                "optimization_relevance": "agents",
                "reasoning": "The instructions likely caused extra friction.",
            }
        )
    )

    assert payload["task_success"] == 0.8
    assert payload["optimization_relevance"] == "agents"


def test_parse_judge_response_rejects_invalid_output():
    try:
        codex_interactive_scoring.parse_judge_response("not-json")
    except ValueError as exc:
        assert "valid JSON" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_merge_interactive_scores_combines_heuristics_and_judge():
    result = codex_interactive_scoring.merge_interactive_scores(
        heuristic_scores={
            "task_completed": True,
            "workflow_compliance": 1.0,
            "user_friction": 0.0,
            "efficiency": 0.8,
        },
        judge_scores={
            "task_success": 0.9,
            "user_friction": 0.2,
            "workflow_compliance": 0.7,
            "efficiency": 0.6,
            "optimization_relevance": "config",
            "reasoning": "The task succeeded but configuration could reduce extra steps.",
        },
    )

    assert result["task_success"] == 0.9
    assert result["optimization_relevance"] == "config"
    assert result["workflow_compliance"] == 0.7


def test_main_missing_wandb_api_key_writes_stderr(monkeypatch, capsys):
    monkeypatch.setattr(codex_interactive_scoring, "ensure_wandb_api_key", lambda: None)

    rc = codex_interactive_scoring.main([])

    out = capsys.readouterr()
    assert rc == 2
    assert "WANDB_API_KEY" in out.err
