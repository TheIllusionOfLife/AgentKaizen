"""Live E2E tests for Claude Code one-shot and session analysis.

All tests require the ``claude`` binary and real Claude Code sessions on disk.
They are skipped automatically in CI environments where neither is available.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

_CLAUDE_AVAILABLE = shutil.which("claude") is not None
_CLAUDE_SESSIONS_EXIST = any(
    pathlib.Path("~/.claude/projects").expanduser().glob("*/*.jsonl")
)
_CI = bool(
    __import__("os").environ.get("CI") or __import__("os").environ.get("GITHUB_ACTIONS")
)

skip_no_claude = pytest.mark.skipif(
    not _CLAUDE_AVAILABLE or _CI, reason="claude binary not found or running in CI"
)
skip_no_sessions = pytest.mark.skipif(
    not _CLAUDE_SESSIONS_EXIST or _CI,
    reason="no Claude Code session files found or running in CI",
)


def _agentkaizen_cmd(*args: str) -> list[str]:
    """Return the agentkaizen CLI command using uv run for correct venv resolution."""
    return ["uv", "run", "--group", "dev", "agentkaizen", *args]


@skip_no_claude
def test_oneshot_claude_code():
    """agentkaizen run --agent claude-code produces non-empty output."""
    result = subprocess.run(
        _agentkaizen_cmd(
            "run",
            "--agent",
            "claude-code",
            "--prompt",
            "List the files in the current directory and tell me which file is most recently modified.",
        ),
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(pathlib.Path(__file__).parent.parent),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert result.stdout.strip(), "Expected non-empty output from claude-code"


@skip_no_sessions
def test_session_sync_claude_code():
    """agentkaizen session sync --agent claude-code --once parses real sessions."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = pathlib.Path(tmpdir) / "state.json"
        result = subprocess.run(
            _agentkaizen_cmd(
                "session",
                "sync",
                "--agent",
                "claude-code",
                "--once",
                "--state-file",
                str(state_file),
            ),
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(pathlib.Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        # First run seeds state (uploads=0), second run may process sessions.
        summary_line = (
            result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        )
        if summary_line:
            summary = json.loads(summary_line)
            assert "state_file" in summary or "seeded" in summary


@skip_no_sessions
def test_session_score_claude_code():
    """Parse a real Claude Code session and score it; summary must be readable."""
    from agentkaizen.claude_code_session import (
        DEFAULT_CLAUDE_SESSION_ROOT,
        build_claude_code_trace,
        discover_claude_sessions,
    )
    from agentkaizen.session_scoring import (
        format_score_summary,
        score_interactive_heuristics,
    )

    sessions = discover_claude_sessions(DEFAULT_CLAUDE_SESSION_ROOT)
    assert sessions, "No sessions found"

    trace = build_claude_code_trace(sessions[0]["path"])
    assert "session_id" in trace
    assert "user_task" in trace
    assert "messages" in trace
    assert "tool_calls" in trace
    assert "token_usage" in trace

    scores = score_interactive_heuristics(trace)
    assert 0.0 <= scores["task_success_estimate"] <= 1.0
    assert 0.0 <= scores["workflow_compliance"] <= 1.0

    summary = format_score_summary(
        {
            **scores,
            "derived_user_task": trace.get("user_task", ""),
            "friction_signals": [],
            "suspicious_signals": [],
            "workflow_failures": [],
            "recommended_changes": [],
            "reasoning": "",
            "heuristics": scores,
        }
    )
    assert "Task:" in summary
    assert "Outcome:" in summary
