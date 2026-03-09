"""Tests for agentkaizen.runners: command assembly and output parsing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentkaizen.runners.base import AgentResult, AgentRunError
from agentkaizen.runners.claude_code import ClaudeCodeRunner
from agentkaizen.runners.codex import CodexRunner
from agentkaizen.runners.registry import RUNNERS, get_runner


# ---------------------------------------------------------------------------
# CodexRunner.build_command
# ---------------------------------------------------------------------------


def test_codex_runner_build_command_basic():
    runner = CodexRunner()
    cmd = runner.build_command("do the thing")
    assert cmd[0] == "codex"
    assert "exec" in cmd
    assert "--json" in cmd
    assert cmd[-1] == "do the thing"


def test_codex_runner_build_command_with_model_and_sandbox():
    runner = CodexRunner(model="o3", sandbox="workspace-write")
    cmd = runner.build_command("hello")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "o3"
    assert "--sandbox" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"


def test_codex_runner_build_command_with_workspace():
    runner = CodexRunner()
    cmd = runner.build_command("hello", workspace=Path("/tmp/ws"))
    assert "-C" in cmd
    assert cmd[cmd.index("-C") + 1] == "/tmp/ws"


def test_codex_runner_build_command_skip_git_repo_check():
    runner = CodexRunner(skip_git_repo_check=True)
    cmd = runner.build_command("hello")
    assert "--skip-git-repo-check" in cmd


def test_codex_runner_build_command_no_skip_git_repo_check_by_default():
    runner = CodexRunner()
    cmd = runner.build_command("hello")
    assert "--skip-git-repo-check" not in cmd


def test_codex_runner_build_command_extra_args():
    runner = CodexRunner(extra_args=["--full-auto"])
    cmd = runner.build_command("hello")
    assert "--full-auto" in cmd


# ---------------------------------------------------------------------------
# CodexRunner.run — happy path
# ---------------------------------------------------------------------------


def _make_jsonl_stdout(final_message: str) -> str:
    lines = [
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": final_message},
            }
        ),
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 3}}
        ),
    ]
    return "\n".join(lines)


def test_codex_runner_run_returns_agent_result(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        return SimpleNamespace(
            returncode=0,
            stdout=_make_jsonl_stdout("hello from codex"),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CodexRunner()
    result = runner.run("my prompt")

    assert isinstance(result, AgentResult)
    assert result.final_message == "hello from codex"
    assert result.returncode == 0
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens == 3


def test_codex_runner_run_passes_workspace_to_command(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout=_make_jsonl_stdout("ok"), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CodexRunner()
    runner.run("prompt", workspace=Path("/tmp/workspace"))

    assert "-C" in captured["cmd"]
    assert "/tmp/workspace" in captured["cmd"]


def test_codex_runner_run_raises_agent_run_error_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CodexRunner()
    with pytest.raises(AgentRunError, match="timed out"):
        runner.run("prompt", timeout_seconds=1)


# ---------------------------------------------------------------------------
# ClaudeCodeRunner.build_command
# ---------------------------------------------------------------------------


def test_claude_code_runner_build_command_basic():
    runner = ClaudeCodeRunner()
    cmd = runner.build_command("do the thing")
    assert "claude" in cmd
    assert "-p" in cmd
    assert "do the thing" in cmd
    assert "--output-format" in cmd
    assert "json" in cmd


def test_claude_code_runner_build_command_with_model():
    runner = ClaudeCodeRunner(model="claude-opus-4-6")
    cmd = runner.build_command("hello")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# ClaudeCodeRunner.run — happy path
# ---------------------------------------------------------------------------


def _make_claude_stdout(result_text: str, is_error: bool = False) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "result": result_text,
            "is_error": is_error,
            "duration_ms": 123,
            "total_cost_usd": 0.01,
        }
    )


def test_claude_code_runner_run_returns_agent_result(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd, env=None):
        return SimpleNamespace(
            returncode=0,
            stdout=_make_claude_stdout("hello from claude"),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = ClaudeCodeRunner()
    result = runner.run("my prompt")

    assert isinstance(result, AgentResult)
    assert result.final_message == "hello from claude"
    assert result.returncode == 0


def test_claude_code_runner_run_raises_on_is_error(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd, env=None):
        return SimpleNamespace(
            returncode=0,
            stdout=_make_claude_stdout("oops", is_error=True),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = ClaudeCodeRunner()
    with pytest.raises(AgentRunError, match="error"):
        runner.run("prompt")


def test_claude_code_runner_run_raises_on_invalid_json(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd, env=None):
        return SimpleNamespace(returncode=0, stdout="not json", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = ClaudeCodeRunner()
    with pytest.raises(AgentRunError, match="not valid JSON"):
        runner.run("prompt")


def test_claude_code_runner_run_raises_agent_run_error_on_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout, cwd, env=None):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = ClaudeCodeRunner()
    with pytest.raises(AgentRunError, match="timed out"):
        runner.run("prompt", timeout_seconds=1)


def test_claude_code_runner_strips_claudecode_env(monkeypatch):
    """CLAUDECODE env var must be removed so nested claude -p calls don't hang."""
    captured: dict = {}

    def fake_run(cmd, capture_output, text, timeout, cwd, env=None):
        captured["env"] = env
        return SimpleNamespace(
            returncode=0,
            stdout=_make_claude_stdout("ok"),
            stderr="",
        )

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = ClaudeCodeRunner()
    runner.run("prompt")

    assert captured.get("env") is not None
    assert "CLAUDECODE" not in captured["env"]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_get_runner_codex_returns_codex_runner():
    runner = get_runner("codex")
    assert isinstance(runner, CodexRunner)
    assert runner.name == "codex"


def test_get_runner_claude_code_returns_claude_code_runner():
    runner = get_runner("claude-code")
    assert isinstance(runner, ClaudeCodeRunner)
    assert runner.name == "claude-code"


def test_get_runner_with_kwargs():
    runner = get_runner("codex", model="o3", sandbox="read-only")
    assert isinstance(runner, CodexRunner)
    assert runner.model == "o3"
    assert runner.sandbox == "read-only"


def test_get_runner_unknown_raises_value_error():
    with pytest.raises(ValueError, match="Unknown agent runner"):
        get_runner("unknown-agent")


def test_runners_registry_contains_expected_keys():
    assert "codex" in RUNNERS
    assert "claude-code" in RUNNERS
