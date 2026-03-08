"""Tests for _trace_log local JSONL trace persistence."""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentkaizen._trace_log import TRACE_SCHEMA_VERSION, append_trace, read_traces


def test_append_and_read_round_trip(tmp_path):
    log_path = tmp_path / "traces.jsonl"

    append_trace(
        {"prompt": "hello", "result": "ok"},
        op_name="test_op",
        log_path=log_path,
    )

    traces = read_traces(log_path=log_path)
    assert len(traces) == 1
    assert traces[0]["op_name"] == "test_op"
    assert traces[0]["output"]["prompt"] == "hello"
    assert traces[0]["version"] == TRACE_SCHEMA_VERSION
    assert "started_at" in traces[0]


def test_append_multiple_traces(tmp_path):
    log_path = tmp_path / "traces.jsonl"

    for i in range(3):
        append_trace({"idx": i}, op_name=f"op_{i}", log_path=log_path)

    traces = read_traces(log_path=log_path, limit=100)
    assert len(traces) == 3


def test_filter_by_op_name_substring(tmp_path):
    log_path = tmp_path / "traces.jsonl"

    append_trace({"a": 1}, op_name="run_codex_exec_traced", log_path=log_path)
    append_trace({"b": 2}, op_name="ingest_interactive_session_traced", log_path=log_path)
    append_trace({"c": 3}, op_name="run_codex_exec_traced", log_path=log_path)

    traces = read_traces(
        log_path=log_path, op_name_substring="run_codex_exec_traced"
    )
    assert len(traces) == 2
    assert all("run_codex_exec_traced" in t["op_name"] for t in traces)


def test_sort_by_started_at_desc(tmp_path):
    log_path = tmp_path / "traces.jsonl"

    # Write entries with explicit started_at to control order
    for i, ts in enumerate(
        ["2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z", "2026-01-02T00:00:00Z"]
    ):
        entry = {
            "version": 1,
            "op_name": f"op_{i}",
            "started_at": ts,
            "output": {"idx": i},
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    traces = read_traces(
        log_path=log_path,
        sort_by=[{"field": "started_at", "direction": "desc"}],
    )
    timestamps = [t["started_at"] for t in traces]
    assert timestamps == sorted(timestamps, reverse=True)


def test_limit_behavior(tmp_path):
    log_path = tmp_path / "traces.jsonl"

    for i in range(10):
        append_trace({"idx": i}, op_name="op", log_path=log_path)

    traces = read_traces(log_path=log_path, limit=3)
    assert len(traces) == 3


def test_directory_auto_creation(tmp_path):
    log_path = tmp_path / "deep" / "nested" / "traces.jsonl"

    append_trace({"x": 1}, op_name="test", log_path=log_path)

    assert log_path.exists()
    traces = read_traces(log_path=log_path)
    assert len(traces) == 1


def test_read_nonexistent_returns_empty(tmp_path):
    log_path = tmp_path / "nonexistent.jsonl"
    traces = read_traces(log_path=log_path)
    assert traces == []


def test_tolerates_malformed_lines(tmp_path):
    log_path = tmp_path / "traces.jsonl"
    log_path.write_text(
        "not-json\n"
        + json.dumps(
            {
                "version": 1,
                "op_name": "valid",
                "started_at": "2026-01-01T00:00:00Z",
                "output": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    traces = read_traces(log_path=log_path)
    assert len(traces) == 1
    assert traces[0]["op_name"] == "valid"
