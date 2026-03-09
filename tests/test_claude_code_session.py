"""Unit tests for agentkaizen.claude_code_session."""

from __future__ import annotations

import json
import pathlib
import tempfile
from typing import Any

import agentkaizen.claude_code_session as ccs
from agentkaizen.session_sync import _load_tool_command, _load_tool_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: pathlib.Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=True) for r in records) + "\n",
        encoding="utf-8",
    )


def _user_record(content: str | list, ts: str = "2024-01-01T00:00:00Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "sessionId": "sess-001",
        "cwd": "/home/user/project",
        "gitBranch": "main",
        "version": "1.2.3",
        "message": {"role": "user", "content": content},
    }


def _assistant_record(
    texts: list[str],
    tool_uses: list[dict] | None = None,
    stop_reason: str = "end_turn",
    ts: str = "2024-01-01T00:01:00Z",
    usage: dict | None = None,
) -> dict:
    content: list[dict] = [{"type": "text", "text": t} for t in texts]
    if tool_uses:
        content.extend(tool_uses)
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "content": content,
            "stop_reason": stop_reason,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5},
        },
    }


def _tool_use_block(name: str, tool_id: str, input_dict: dict) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": input_dict}


def _tool_result_block(tool_use_id: str, output: str, is_error: bool = False) -> dict:
    blk: dict = {"type": "tool_result", "tool_use_id": tool_use_id, "content": output}
    if is_error:
        blk["is_error"] = True
    return blk


# ---------------------------------------------------------------------------
# Discovery tests
# ---------------------------------------------------------------------------


def test_discover_sessions_finds_jsonl_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        proj = root / "project-slug"
        proj.mkdir()
        sess = proj / "abc123.jsonl"
        _write_jsonl(sess, [_user_record("hello")])

        results = ccs.discover_claude_sessions(root)
        assert len(results) == 1
        assert results[0]["path"] == sess.resolve()


def test_discover_sessions_skips_subagent_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        proj = root / "project-slug"
        sub = proj / "abc123" / "subagents"
        sub.mkdir(parents=True)
        _write_jsonl(sub / "agent-1.jsonl", [_user_record("sub task")])
        # Also add a real session at the project level
        _write_jsonl(proj / "main.jsonl", [_user_record("main task")])

        results = ccs.discover_claude_sessions(root)
        paths = [r["path"].name for r in results]
        assert "main.jsonl" in paths
        assert "agent-1.jsonl" not in paths


def test_discover_sessions_skips_symlinks():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        proj = root / "project-slug"
        proj.mkdir()
        real = root / "real.jsonl"
        _write_jsonl(real, [_user_record("real")])
        link = proj / "link.jsonl"
        link.symlink_to(real)

        results = ccs.discover_claude_sessions(root)
        paths = [r["path"].name for r in results]
        assert "link.jsonl" not in paths


def test_discover_sessions_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        results = ccs.discover_claude_sessions(root)
        assert results == []


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------


def test_parse_user_text_message():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        _write_jsonl(path, [_user_record("Hello, do this task")])

        trace = ccs.build_claude_code_trace(path)
        msgs = trace["messages"]
        assert any(m["role"] == "user" and "Hello" in m["content"] for m in msgs)


def test_parse_assistant_text_message():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        _write_jsonl(
            path,
            [
                _user_record("Run a task"),
                _assistant_record(["I will complete that for you."]),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        assistant_msgs = [m for m in trace["messages"] if m["role"] == "assistant"]
        assert len(assistant_msgs) == 1
        assert "complete" in assistant_msgs[0]["content"]


def test_parse_tool_use_and_tool_result():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        tool_use = _tool_use_block("Bash", "tu-1", {"command": "ls -la"})
        tool_result_content = [_tool_result_block("tu-1", "file1.txt\nfile2.txt")]
        _write_jsonl(
            path,
            [
                _user_record("List files"),
                _assistant_record(["I will list them"], tool_uses=[tool_use]),
                _user_record(tool_result_content),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        tool_calls = trace["tool_calls"]
        # Should have: invocation + output
        invocations = [tc for tc in tool_calls if tc["name"] == "Bash"]
        outputs = [tc for tc in tool_calls if tc["name"] == "function_call_output"]
        assert len(invocations) == 1
        assert len(outputs) == 1
        assert outputs[0]["call_id"] == "tu-1"


def test_aggregate_token_usage():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        _write_jsonl(
            path,
            [
                _user_record("Task A"),
                _assistant_record(
                    ["Response A"],
                    usage={"input_tokens": 100, "output_tokens": 50},
                ),
                _user_record("Task B"),
                _assistant_record(
                    ["Response B"],
                    usage={"input_tokens": 200, "output_tokens": 80},
                ),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        usage = trace["token_usage"]
        assert usage["input_tokens"] == 300
        assert usage["output_tokens"] == 130
        assert usage["total_tokens"] == 430


def test_skip_progress_records():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        progress_record = {"type": "progress", "timestamp": "2024-01-01T00:00:00Z"}
        _write_jsonl(
            path,
            [
                _user_record("Do something"),
                progress_record,
                progress_record,
                progress_record,
                _assistant_record(["Done."]),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        # Progress records should not appear in messages or tool_calls
        assert len(trace["messages"]) == 2  # user + assistant
        assert trace["ingest_metadata"]["malformed_lines"] == 0


def test_malformed_jsonl_lines_skipped():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        path.write_text(
            json.dumps(_user_record("valid")) + "\n"
            "NOT JSON AT ALL\n"
            "{broken\n" + json.dumps(_assistant_record(["ok"])) + "\n",
            encoding="utf-8",
        )

        trace = ccs.build_claude_code_trace(path)
        assert trace["ingest_metadata"]["malformed_lines"] == 2
        assert len(trace["messages"]) == 2


def test_unknown_record_types_skipped():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        unknown = {
            "type": "queue-operation",
            "timestamp": "2024-01-01T00:00:00Z",
            "data": "something",
        }
        _write_jsonl(
            path,
            [_user_record("Do something"), unknown, _assistant_record(["Done."])],
        )

        trace = ccs.build_claude_code_trace(path)
        assert len(trace["messages"]) == 2


def test_interrupted_session_no_last_assistant():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        # Only a user message — session was interrupted before assistant responded
        _write_jsonl(path, [_user_record("Start a long task")])

        trace = ccs.build_claude_code_trace(path)
        assert trace["status"] == "incomplete"
        assert trace["status_reason"] == "no_signal"


# ---------------------------------------------------------------------------
# Analysis / completion detection tests
# ---------------------------------------------------------------------------


def test_detect_workflow_signals():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        tool_use_git = _tool_use_block(
            "Bash", "tu-git", {"command": "git checkout -b feat/new"}
        )
        tool_use_test = _tool_use_block("Bash", "tu-test", {"command": "uv run pytest"})
        _write_jsonl(
            path,
            [
                _user_record("Implement a feature"),
                _assistant_record(
                    ["Creating branch"],
                    tool_uses=[tool_use_git],
                ),
                _assistant_record(
                    ["Running tests"],
                    tool_uses=[tool_use_test],
                ),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        analysis = trace["analysis"]
        assert analysis["branch_created"] is True
        assert analysis["ran_tests"] is True


def test_detect_tool_errors():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        tool_use = _tool_use_block("Bash", "tu-err", {"command": "bad command"})
        tool_result = [_tool_result_block("tu-err", "command not found", is_error=True)]
        _write_jsonl(
            path,
            [
                _user_record("Do something"),
                _assistant_record(["Trying"], tool_uses=[tool_use]),
                _user_record(tool_result),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        assert trace["analysis"]["error_count"] > 0


def test_detect_completion_end_turn():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        _write_jsonl(
            path,
            [
                _user_record("Do a task"),
                _assistant_record(["Done."], stop_reason="end_turn"),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        assert trace["status"] == "complete"
        assert trace["status_reason"] == "end_turn"


def test_detect_completion_last_prompt():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        last_prompt_record = {
            "type": "last-prompt",
            "timestamp": "2024-01-01T00:05:00Z",
        }
        _write_jsonl(
            path,
            [
                _user_record("Do a task"),
                # No end_turn stop_reason, but last-prompt record present
                _assistant_record(["Working on it..."], stop_reason="max_tokens"),
                last_prompt_record,
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        assert trace["status"] == "complete"
        assert trace["status_reason"] == "last_prompt"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_scoring_works_with_claude_code_trace():
    from agentkaizen.session_scoring import score_interactive_heuristics

    with tempfile.TemporaryDirectory() as tmpdir:
        path = pathlib.Path(tmpdir) / "s.jsonl"
        _write_jsonl(
            path,
            [
                _user_record("Implement feature X"),
                _assistant_record(["Done."], stop_reason="end_turn"),
            ],
        )

        trace = ccs.build_claude_code_trace(path)
        scores = score_interactive_heuristics(trace)
        assert "task_success_estimate" in scores
        assert "workflow_compliance" in scores
        assert 0.0 <= scores["task_success_estimate"] <= 1.0


def test_load_tool_command_handles_bash():
    """_load_tool_command recognizes 'Bash' name and 'command' key."""
    call_with_command_key = {
        "name": "Bash",
        "arguments": json.dumps({"command": "pytest tests/"}),
    }
    result = _load_tool_command(call_with_command_key)
    assert result == "pytest tests/"

    call_with_cmd_key = {
        "name": "Bash",
        "arguments": json.dumps({"cmd": "git status"}),
    }
    result2 = _load_tool_command(call_with_cmd_key)
    assert result2 == "git status"

    # Original exec_command still works
    call_exec = {
        "name": "exec_command",
        "arguments": json.dumps({"cmd": "ls -la"}),
    }
    result3 = _load_tool_command(call_exec)
    assert result3 == "ls -la"


def test_load_tool_output_handles_dict_output():
    """_load_tool_output handles dict output (Claude Code error payloads)."""
    call_dict_output = {
        "name": "function_call_output",
        "output": {"error": "command not found", "exit_code": 1},
    }
    result = _load_tool_output(call_dict_output)
    assert result["exit_code"] == 1
