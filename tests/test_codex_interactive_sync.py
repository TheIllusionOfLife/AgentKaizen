import json
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import agentkaizen.session_sync as codex_interactive_sync


def test_load_session_index_rows(tmp_path):
    index = tmp_path / "session_index.jsonl"
    index.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "s1",
                        "thread_name": "a",
                        "updated_at": "2026-03-06T01:00:00Z",
                    }
                ),
                json.dumps(
                    {
                        "id": "s2",
                        "thread_name": "b",
                        "updated_at": "2026-03-06T02:00:00Z",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_interactive_sync.load_session_index(index)

    assert [row["id"] for row in rows] == ["s1", "s2"]


def test_find_session_file_for_id(tmp_path):
    session_root = tmp_path / "sessions"
    target_dir = session_root / "2026" / "03" / "06"
    target_dir.mkdir(parents=True)
    session_id = "019cbd88-49e0-7761-920d-8aba7d7db401"
    target = target_dir / f"rollout-2026-03-06T00-00-00-{session_id}.jsonl"
    target.write_text("", encoding="utf-8")

    found = codex_interactive_sync.find_session_file(session_root, session_id)

    assert found == target


def test_build_interactive_trace_extracts_messages_and_usage(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "abc",
                            "cwd": "/repo",
                            "cli_version": "0.110.0",
                            "timestamp": "2026-03-06T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": "hello",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 10,
                                    "output_tokens": 5,
                                }
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:03Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["source"] == "codex_interactive"
    assert trace["session_id"] == "abc"
    assert trace["thread_name"] == "demo"
    assert trace["status"] == "complete"
    assert trace["completed_at"] == "2026-03-06T00:00:03Z"
    assert trace["updated_at"] == "2026-03-06T00:00:03Z"
    assert trace["token_usage"]["input_tokens"] == 10
    assert trace["token_usage"]["output_tokens"] == 5
    assert trace["messages"][0]["content"] == "hello"


def test_build_interactive_trace_preserves_multimodal_content_blocks(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "abc",
                            "cwd": "/repo",
                            "cli_version": "0.110.0",
                            "timestamp": "2026-03-06T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Review this image"},
                                {
                                    "type": "input_image",
                                    "image_url": "file:///tmp/diagram.png",
                                },
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["modalities"] == ["text", "image"]
    assert trace["messages"][0]["content"] == "Review this image"
    assert trace["messages"][0]["content_blocks"] == [
        {"type": "input_text", "text": "Review this image"},
        {"type": "input_image", "image_url": "file:///tmp/diagram.png"},
    ]
    assert trace["user_task"] == "Review this image"


def test_build_interactive_trace_sanitizes_image_paths_in_content_blocks(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "abc", "cwd": "/repo"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Check this image"},
                                {
                                    "type": "input_image",
                                    "image_path": str(
                                        tmp_path / "nested" / "diagram.png"
                                    ),
                                },
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["messages"][0]["content_blocks"] == [
        {"type": "input_text", "text": "Check this image"},
        {"type": "input_image", "image_path": "diagram.png"},
    ]


def test_build_interactive_trace_derives_user_task_and_compact_summary(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "abc",
                            "cwd": "/repo",
                            "cli_version": "0.110.0",
                            "timestamp": "2026-03-06T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "# AGENTS.md instructions for /repo\n<INSTRUCTIONS>\nVery long boilerplate",
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "text": "Show me a demo of what's implemented in PR #4.",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:03Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": "I found the relevant merged PR and prepared a live demo.",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:04Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="Demo PR #4 implementation",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["user_task"] == "Show me a demo of what's implemented in PR #4."
    assert "Show me a demo" in trace["analysis_summary"]
    assert "# AGENTS.md instructions" not in trace["analysis_summary"]


def test_build_interactive_trace_marks_corrections_and_command_categories(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "abc", "cwd": "/repo"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": "I will explain the repo.",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": "Actually, explain the architecture instead.",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:03Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps({"cmd": "uv run pytest"}),
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["analysis"]["user_correction_count"] == 1
    assert trace["analysis"]["command_categories"]["test"] == 1
    assert trace["analysis"]["completion_signal_source"] == "incomplete"


def test_build_interactive_trace_detects_clarification_turns_with_confirmation(
    tmp_path,
):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "abc", "cwd": "/repo"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": "Should I update README.md or AGENTS.md?",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": "Use README.md.",
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["analysis"]["clarification_question_count"] == 1


def test_build_interactive_trace_prefers_discovery_updated_at(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "abc",
                            "cwd": "/repo",
                            "cli_version": "0.110.0",
                            "timestamp": "2026-03-06T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:05Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
        discovery_metadata={"updated_at": "2026-03-06T00:00:09Z"},
    )

    assert trace["completed_at"] == "2026-03-06T00:00:05Z"
    assert trace["updated_at"] == "2026-03-06T00:00:09Z"


def test_build_interactive_trace_backfills_empty_thread_name_from_user_task(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "abc",
                            "cwd": "/repo",
                            "cli_version": "0.110.0",
                            "timestamp": "2026-03-06T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "# AGENTS.md instructions for /repo\n<INSTRUCTIONS>\nVery long boilerplate",
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "text": "Please demo the merged workflow.",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:03Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["user_task"] == "Please demo the merged workflow."
    assert trace["thread_name"] == "Please demo the merged workflow."


def test_redaction_applies_default_patterns(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-03-06T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "token sk-abc123 and user@example.com",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    text = trace["messages"][0]["content"]
    assert "sk-abc123" not in text
    assert "user@example.com" not in text
    assert "[REDACTED]" in text


def test_redaction_handles_quoted_api_key():
    redactor = codex_interactive_sync.build_redactor([])
    redacted = redactor('api-key: "sk-abc123"')
    assert "sk-abc123" not in redacted
    assert "[REDACTED]" in redacted


def test_redaction_extra_patterns_do_not_reemit_capture_groups():
    redactor = codex_interactive_sync.build_redactor([r"(secret)-value"])
    redacted = redactor("secret-value")
    assert redacted == "[REDACTED]"


def test_build_interactive_trace_applies_builtin_pii_redaction(monkeypatch, tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-03-06T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": "email user@example.com",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        codex_interactive_sync,
        "apply_builtin_pii_redaction",
        lambda value, enabled=True: {
            **value,
            "messages": [{**value["messages"][0], "content": "[REDACTED]"}],
        },
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["messages"][0]["content"] == "[REDACTED]"


def test_build_interactive_trace_sanitizes_path_fields(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-03-06T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "abc",
                    "cwd": "/Users/alice/private-project",
                    "cli_version": "0.110.0",
                    "timestamp": "2026-03-06T00:00:00Z",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert trace["cwd"] == "/Users/[REDACTED]/private-project"
    assert trace["ingest_metadata"][
        "session_file"
    ] == codex_interactive_sync._sanitize_path(str(session_file))


def test_select_sessions_to_process_is_idempotent():
    index_rows = [
        {
            "id": "s1",
            "thread_name": "a",
            "updated_at": "2026-03-06T01:00:00Z",
        },
        {
            "id": "s2",
            "thread_name": "b",
            "updated_at": "2026-03-06T02:00:00Z",
        },
    ]
    state = {
        "last_processed_updated_at": "2026-03-06T00:30:00Z",
        "processed_session_ids": ["s1"],
    }

    selected = codex_interactive_sync.select_sessions_to_process(
        index_rows=index_rows,
        state=state,
        now=datetime(2026, 3, 6, 3, 0, 0, tzinfo=UTC),
    )

    assert [row["id"] for row in selected] == ["s2"]


def test_select_sessions_to_process_keeps_equal_timestamp_if_not_processed():
    index_rows = [
        {
            "id": "s1",
            "thread_name": "a",
            "updated_at": "2026-03-06T01:00:00Z",
        }
    ]
    state = {
        "last_processed_updated_at": "2026-03-06T01:00:00Z",
        "processed_session_ids": [],
    }

    selected = codex_interactive_sync.select_sessions_to_process(
        index_rows=index_rows,
        state=state,
        now=datetime(2026, 3, 6, 2, 0, 0, tzinfo=UTC),
    )

    assert [row["id"] for row in selected] == ["s1"]


def test_run_sync_once_bootstraps_state_without_backfill(monkeypatch, tmp_path):
    index_file = tmp_path / "session_index.jsonl"
    state_file = tmp_path / "state.json"
    index_file.write_text(
        json.dumps(
            {
                "id": "s1",
                "thread_name": "demo",
                "updated_at": "2026-03-06T05:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(codex_interactive_sync, "weave_op", lambda **kw: lambda fn: fn)
    monkeypatch.setattr(codex_interactive_sync, "append_trace", lambda *a, **kw: None)

    summary = codex_interactive_sync._run_sync_once(
        session_root=tmp_path / "sessions",
        index_file=index_file,
        state_file=state_file,
        quiet_seconds=30,
        redactor=codex_interactive_sync.build_redactor([]),
        redaction_enabled=True,
    )

    saved_state = codex_interactive_sync.load_sync_state(state_file)
    assert summary["selected"] == 0
    assert summary["uploaded"] == 0
    assert saved_state["last_processed_updated_at"] == "2026-03-06T05:00:00Z"


def test_main_runs_locally_when_wandb_api_key_missing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(codex_interactive_sync, "ensure_wandb_api_key", lambda: None)
    monkeypatch.setattr(codex_interactive_sync, "HAS_WEAVE", False)
    # Set up minimal state so --once doesn't fail
    state_file = tmp_path / "state.json"
    index_file = tmp_path / "session_index.jsonl"
    index_file.write_text("", encoding="utf-8")
    session_root = tmp_path / "sessions"
    session_root.mkdir()

    rc = codex_interactive_sync.main(
        [
            "--once",
            "--session-root",
            str(session_root),
            "--index-file",
            str(index_file),
            "--state-file",
            str(state_file),
        ]
    )

    out = capsys.readouterr()
    assert rc == 0
    assert "local-only mode" in out.err


def test_recover_orphaned_sessions_returns_completed_session_not_in_index(tmp_path):
    session_root = tmp_path / "sessions"
    session_dir = session_root / "2026" / "03" / "06"
    session_dir.mkdir(parents=True)
    session_id = "019cc148-d4d9-71c3-80e7-5b741ebab085"
    session_file = session_dir / f"rollout-2026-03-06T00-00-00-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T03:55:33.497Z",
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "timestamp": "2026-03-06T03:55:01.728Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T03:55:34.000Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "is gpt-5.4 better than gpt-codex-5.3 for coding?",
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T03:58:22.145Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_interactive_sync.recover_orphaned_sessions(
        session_root=session_root,
        indexed_session_ids=set(),
        state={"processed_session_ids": []},
        now=datetime(2026, 3, 6, 4, 0, 0, tzinfo=UTC),
        quiet_seconds=0,
    )

    assert rows == [
        {
            "id": session_id,
            "thread_name": "is gpt-5.4 better than gpt-codex-5.3 for coding?",
            "updated_at": "2026-03-06T03:58:22.145Z",
            "discovery_source": "recovered",
            "index_present": False,
            "session_file": str(session_file),
        }
    ]


def test_collect_sessions_to_process_dedupes_index_and_recovered_rows(tmp_path):
    session_root = tmp_path / "sessions"
    session_dir = session_root / "2026" / "03" / "06"
    session_dir.mkdir(parents=True)
    session_id = "s1"
    session_file = session_dir / f"rollout-2026-03-06T00-00-00-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T01:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "timestamp": "2026-03-06T01:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T01:01:00Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    selected = codex_interactive_sync.collect_sessions_to_process(
        session_root=session_root,
        index_rows=[
            {
                "id": session_id,
                "thread_name": "from-index",
                "updated_at": "2026-03-06T01:01:00Z",
            }
        ],
        state={"processed_session_ids": []},
        now=datetime(2026, 3, 6, 2, 0, 0, tzinfo=UTC),
        quiet_seconds=0,
    )

    assert len(selected) == 1
    assert selected[0]["id"] == session_id
    assert selected[0]["thread_name"] == "from-index"


def test_build_interactive_trace_adds_analysis_fields(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "abc",
                            "cwd": "/repo",
                            "cli_version": "0.110.0",
                            "timestamp": "2026-03-06T00:00:00Z",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "please fix this bug"}
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "agent_message",
                            "message": "I am checking tests and will create a branch.",
                            "phase": "commentary",
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:03Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": "call-1",
                            "arguments": json.dumps(
                                {"cmd": "git checkout -b fix/demo"}
                            ),
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:04Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": "call-2",
                            "arguments": json.dumps({"cmd": "uv run pytest"}),
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:05Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    analysis = trace["analysis"]
    assert analysis["user_turn_count"] == 1
    assert analysis["assistant_turn_count"] == 1
    assert analysis["commentary_count"] == 1
    assert analysis["tool_call_count"] == 2
    assert analysis["branch_created"] is True
    assert analysis["used_uv"] is True
    assert analysis["ran_tests"] is True
    assert analysis["task_completed"] is True
    assert "please fix this bug" in trace["analysis_summary"]


def test_build_interactive_trace_redacts_thread_name(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-03-06T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "abc",
                    "cwd": "/repo",
                    "cli_version": "0.110.0",
                    "timestamp": "2026-03-06T00:00:00Z",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="Contact me at user@example.com",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    assert "user@example.com" not in trace["thread_name"]
    assert "[REDACTED]" in trace["thread_name"]
    assert "user@example.com" not in trace["analysis_summary"]


def test_build_interactive_analysis_counts_only_actionable_clarifications():
    analysis = codex_interactive_sync._build_interactive_analysis(
        messages=[
            {
                "role": "assistant",
                "content": "I found the merged PR. Should I run the live demo now?",
                "phase": "answer",
            },
            {
                "role": "user",
                "content": "Yes, please run it.",
                "phase": "",
            },
            {
                "role": "assistant",
                "content": "I found the merged PR and asked myself whether the demo should use recovery mode?",
                "phase": "final_answer",
            },
        ],
        tool_calls=[],
        status="complete",
    )

    assert analysis["clarification_question_count"] == 1


def test_run_sync_once_uploads_multimodal_trace_payload(monkeypatch, tmp_path):
    session_root = tmp_path / "sessions"
    session_dir = session_root / "2026" / "03" / "06"
    session_dir.mkdir(parents=True)
    index_file = tmp_path / "session_index.jsonl"
    state_file = tmp_path / "state.json"
    session_id = "019cc148-d4d9-71c3-80e7-5b741ebab085"
    session_file = session_dir / f"rollout-2026-03-06T00-00-00-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": session_id, "cwd": "/repo"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Review this image"},
                                {
                                    "type": "input_image",
                                    "image_url": "file:///tmp/demo.png",
                                },
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:02Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    index_file.write_text(
        json.dumps(
            {
                "id": session_id,
                "thread_name": "Review this image",
                "updated_at": "2026-03-06T00:00:02Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state_file.write_text(
        json.dumps(
            {
                "last_processed_updated_at": "2026-03-06T00:00:00Z",
                "processed_session_ids": [],
            }
        ),
        encoding="utf-8",
    )

    uploaded = []

    def capturing_op(**_kw):
        def deco(fn):
            def wrapped(trace_payload):
                uploaded.append(trace_payload)
                return fn(trace_payload)

            return wrapped

        return deco

    monkeypatch.setattr(codex_interactive_sync, "weave_op", capturing_op)
    monkeypatch.setattr(codex_interactive_sync, "append_trace", lambda *a, **kw: None)

    summary = codex_interactive_sync._run_sync_once(
        session_root=session_root,
        index_file=index_file,
        state_file=state_file,
        quiet_seconds=0,
        redactor=codex_interactive_sync.build_redactor([]),
        redaction_enabled=True,
    )

    assert summary["uploaded"] == 1
    assert uploaded[-1]["modalities"] == ["text", "image"]
    assert uploaded[-1]["messages"][0]["content_blocks"][1]["type"] == "input_image"


def test_build_interactive_analysis_uses_structured_error_signals_not_keywords():
    analysis = codex_interactive_sync._build_interactive_analysis(
        messages=[
            {
                "role": "assistant",
                "content": "If this fails, I will retry and summarize the error cleanly.",
                "phase": "answer",
            }
        ],
        tool_calls=[
            {
                "name": "exec_command",
                "call_id": "call-1",
                "arguments": json.dumps({"cmd": "uv run pytest"}),
            },
            {
                "name": "function_call_output",
                "call_id": "call-1",
                "output": json.dumps({"exit_code": 1, "stderr": "tests failed"}),
            },
        ],
        status="complete",
    )

    assert analysis["error_count"] == 1


def test_build_interactive_analysis_counts_only_invocations():
    analysis = codex_interactive_sync._build_interactive_analysis(
        messages=[],
        tool_calls=[
            {"name": "exec_command", "arguments": json.dumps({"cmd": "uv run pytest"})},
            {"name": "function_call_output", "output": "ok"},
        ],
        status="complete",
    )

    assert analysis["tool_call_count"] == 1


def test_recover_orphaned_sessions_skips_sessions_before_watermark(tmp_path):
    session_root = tmp_path / "sessions"
    session_dir = session_root / "2026" / "03" / "06"
    session_dir.mkdir(parents=True)
    session_id = "019cc148-old-session"
    session_file = session_dir / f"rollout-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T01:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": session_id},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T01:05:00Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_interactive_sync.recover_orphaned_sessions(
        session_root=session_root,
        indexed_session_ids=set(),
        state={
            "processed_session_ids": [],
            "last_processed_updated_at": "2026-03-06T02:00:00Z",
        },
        now=datetime(2026, 3, 6, 4, 0, 0, tzinfo=UTC),
        quiet_seconds=0,
    )

    assert rows == []


def test_recover_orphaned_sessions_includes_sessions_after_watermark(tmp_path):
    session_root = tmp_path / "sessions"
    session_dir = session_root / "2026" / "03" / "06"
    session_dir.mkdir(parents=True)
    session_id = "019cc148-new-session"
    session_file = session_dir / f"rollout-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T03:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": session_id},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T03:05:00Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_interactive_sync.recover_orphaned_sessions(
        session_root=session_root,
        indexed_session_ids=set(),
        state={
            "processed_session_ids": [],
            "last_processed_updated_at": "2026-03-06T02:00:00Z",
        },
        now=datetime(2026, 3, 6, 4, 0, 0, tzinfo=UTC),
        quiet_seconds=0,
    )

    assert len(rows) == 1
    assert rows[0]["id"] == session_id


def test_recover_orphaned_sessions_skips_sessions_at_watermark(tmp_path):
    session_root = tmp_path / "sessions"
    session_dir = session_root / "2026" / "03" / "06"
    session_dir.mkdir(parents=True)
    session_id = "019cc148-exact-session"
    session_file = session_dir / f"rollout-{session_id}.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T02:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": session_id},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T02:00:00Z",
                        "type": "event_msg",
                        "payload": {"type": "task_complete"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_interactive_sync.recover_orphaned_sessions(
        session_root=session_root,
        indexed_session_ids=set(),
        state={
            "processed_session_ids": [],
            "last_processed_updated_at": "2026-03-06T02:00:00Z",
        },
        now=datetime(2026, 3, 6, 4, 0, 0, tzinfo=UTC),
        quiet_seconds=0,
    )

    assert rows == []


def test_image_url_file_uri_sanitized(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "abc", "cwd": "/repo"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Check image"},
                                {
                                    "type": "input_image",
                                    "image_url": "file:///Users/testuser/images/pic.png",
                                },
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
    )

    url = trace["messages"][0]["content_blocks"][1]["image_url"]
    assert "testuser" not in url
    assert "[REDACTED]" in url


def test_image_url_https_not_sanitized(tmp_path):
    session_file = tmp_path / "rollout.jsonl"
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "abc", "cwd": "/repo"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-06T00:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Check image"},
                                {
                                    "type": "input_image",
                                    "image_url": "https://cdn.test/pic.png",
                                },
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    trace = codex_interactive_sync.build_interactive_trace(
        session_file=session_file,
        thread_name="demo",
        redactor=codex_interactive_sync.build_redactor([]),
        redaction_enabled=False,
    )

    url = trace["messages"][0]["content_blocks"][1]["image_url"]
    assert url == "https://cdn.test/pic.png"


def test_build_interactive_analysis_handles_invalid_shell_syntax():
    analysis = codex_interactive_sync._build_interactive_analysis(
        messages=[],
        tool_calls=[
            {
                "name": "exec_command",
                "arguments": json.dumps({"cmd": 'python -c "unterminated'}),
            }
        ],
        status="complete",
    )

    assert analysis["ran_lint"] is False
    assert analysis["ran_format"] is False
