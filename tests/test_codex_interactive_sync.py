import json
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_interactive_sync


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
    assert trace["token_usage"]["input_tokens"] == 10
    assert trace["token_usage"]["output_tokens"] == 5
    assert trace["messages"][0]["content"] == "hello"


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

    class FakeWeave:
        def op(self):
            def deco(fn):
                return fn

            return deco

    monkeypatch.setattr(codex_interactive_sync, "weave", FakeWeave())

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


def test_main_missing_wandb_api_key_writes_stderr(monkeypatch, capsys):
    monkeypatch.setattr(codex_interactive_sync, "ensure_wandb_api_key", lambda: None)

    rc = codex_interactive_sync.main(["--once"])

    out = capsys.readouterr()
    assert rc == 2
    assert "WANDB_API_KEY" in out.err
    assert out.out == ""
