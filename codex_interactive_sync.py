from __future__ import annotations

import argparse
import json
import logging
import pathlib
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import weave

from codex_weave import DEFAULT_ENTITY, DEFAULT_PROJECT, ensure_wandb_api_key

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ROOT = pathlib.Path("~/.codex/sessions").expanduser()
DEFAULT_INDEX_FILE = pathlib.Path("~/.codex/session_index.jsonl").expanduser()
DEFAULT_STATE_FILE = pathlib.Path("~/.codex/weave_sync_state.json").expanduser()
DEFAULT_POLL_SECONDS = 15
DEFAULT_QUIET_SECONDS = 30
MAX_PROCESSED_SESSION_IDS = 10_000
PARSER_VERSION = 1

DEFAULT_REDACT_PATTERNS = [
    r"sk-[A-Za-z0-9_-]+",
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    r"(?i)(api[_-]?key\s*[=:]\s*['\"]?)([^\s\"']+)",
    r"(?i)(authorization\s*[:=]\s*bearer\s+['\"]?)([^\s\"']+)",
]


def parse_iso8601(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def load_session_index(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if "id" not in row or "updated_at" not in row:
            continue
        rows.append(row)

    rows.sort(key=lambda row: str(row.get("updated_at", "")))
    return rows


def find_session_file(
    session_root: pathlib.Path, session_id: str
) -> pathlib.Path | None:
    matches = sorted(session_root.rglob(f"*{session_id}.jsonl"))
    if not matches:
        return None
    return matches[-1]


def load_sync_state(path: pathlib.Path) -> dict[str, Any]:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                processed_ids = payload.get("processed_session_ids", [])
                if not isinstance(processed_ids, list):
                    processed_ids = []
                return {
                    "last_processed_updated_at": payload.get(
                        "last_processed_updated_at"
                    ),
                    "processed_session_ids": [str(item) for item in processed_ids],
                }
        except json.JSONDecodeError:
            pass
    return {"last_processed_updated_at": None, "processed_session_ids": []}


def save_sync_state(path: pathlib.Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
    )


def select_sessions_to_process(
    *,
    index_rows: list[dict[str, Any]],
    state: dict[str, Any],
    now: datetime | None = None,
    quiet_seconds: int = DEFAULT_QUIET_SECONDS,
) -> list[dict[str, Any]]:
    now_dt = now or datetime.now(UTC)
    quiet_cutoff = now_dt - timedelta(seconds=quiet_seconds)
    last_processed = state.get("last_processed_updated_at")
    processed_ids = set(state.get("processed_session_ids", []))

    selected: list[dict[str, Any]] = []
    for row in index_rows:
        session_id = str(row.get("id", ""))
        updated_at = str(row.get("updated_at", ""))
        if not session_id or not updated_at:
            continue
        if last_processed and updated_at <= str(last_processed):
            continue
        if session_id in processed_ids:
            continue
        try:
            updated_dt = parse_iso8601(updated_at)
        except ValueError:
            continue
        if updated_dt > quiet_cutoff:
            continue
        selected.append(row)
    return selected


def build_redactor(
    extra_patterns: list[str], enabled: bool = True
) -> Callable[[Any], Any]:
    if not enabled:
        return lambda value: value

    compiled = [
        re.compile(pattern) for pattern in [*DEFAULT_REDACT_PATTERNS, *extra_patterns]
    ]

    def redact_text(text: str) -> str:
        redacted = text
        for pattern in compiled:
            redacted = pattern.sub(
                r"\1[REDACTED]" if pattern.groups >= 1 else "[REDACTED]", redacted
            )
        return redacted

    def redact_value(value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        if isinstance(value, dict):
            return {str(k): redact_value(v) for k, v in value.items()}
        return value

    return redact_value


def _as_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=True)


def _sanitize_path(path_value: str) -> str:
    if not path_value:
        return path_value
    home_dir = str(pathlib.Path.home())
    if path_value.startswith(home_dir):
        path_value = path_value.replace(home_dir, "~", 1)
    path_value = re.sub(r"^/Users/[^/]+/", "/Users/[REDACTED]/", path_value)
    path_value = re.sub(r"^/home/[^/]+/", "/home/[REDACTED]/", path_value)
    return path_value


def build_interactive_trace(
    *,
    session_file: pathlib.Path,
    thread_name: str,
    redactor: Callable[[Any], Any],
    redaction_enabled: bool = True,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    session_meta: dict[str, Any] = {}
    token_usage: dict[str, Any] = {}
    malformed_lines = 0
    complete = False

    for raw_line in session_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        if not isinstance(record, dict):
            continue

        record_type = record.get("type")
        payload = record.get("payload", {})
        ts = _as_string(record.get("timestamp"))
        if not isinstance(payload, dict):
            payload = {}

        if record_type == "session_meta":
            session_meta = payload

        if record_type == "response_item":
            payload_type = payload.get("type")
            if payload_type == "message":
                messages.append(
                    {
                        "timestamp": ts,
                        "role": _as_string(payload.get("role")),
                        "content": redactor(_as_string(payload.get("content"))),
                        "phase": _as_string(payload.get("phase")),
                        "source": "response_item",
                    }
                )
            elif payload_type == "function_call":
                tool_calls.append(
                    {
                        "timestamp": ts,
                        "name": _as_string(payload.get("name")),
                        "call_id": _as_string(payload.get("call_id")),
                        "arguments": redactor(_as_string(payload.get("arguments"))),
                    }
                )
            elif payload_type == "function_call_output":
                tool_calls.append(
                    {
                        "timestamp": ts,
                        "name": "function_call_output",
                        "call_id": _as_string(payload.get("call_id")),
                        "output": redactor(_as_string(payload.get("output"))),
                    }
                )

        if record_type == "event_msg":
            payload_type = payload.get("type")
            if payload_type == "token_count":
                info = payload.get("info", {})
                if isinstance(info, dict):
                    total = info.get("total_token_usage", {})
                    if isinstance(total, dict):
                        token_usage = {
                            "input_tokens": int(total.get("input_tokens") or 0),
                            "output_tokens": int(total.get("output_tokens") or 0),
                            "total_tokens": int(total.get("total_tokens") or 0),
                        }
            elif payload_type in {"user_message", "agent_message"}:
                maybe_text = payload.get("text")
                if maybe_text is not None:
                    messages.append(
                        {
                            "timestamp": ts,
                            "role": "user"
                            if payload_type == "user_message"
                            else "assistant",
                            "content": redactor(_as_string(maybe_text)),
                            "phase": "",
                            "source": "event_msg",
                        }
                    )
            elif payload_type == "task_complete":
                complete = True

    status = "complete" if complete else "partial"
    if malformed_lines > 0 and not messages and not tool_calls:
        status = "parse_error"

    return {
        "source": "codex_interactive",
        "session_id": _as_string(session_meta.get("id") or session_file.stem),
        "thread_name": thread_name,
        "cwd": _sanitize_path(redactor(_as_string(session_meta.get("cwd")))),
        "cli_version": _as_string(session_meta.get("cli_version")),
        "started_at": _as_string(session_meta.get("timestamp")),
        "status": status,
        "messages": messages,
        "tool_calls": tool_calls,
        "token_usage": token_usage,
        "ingest_metadata": {
            "parser_version": PARSER_VERSION,
            "redaction_enabled": redaction_enabled,
            "session_file": _sanitize_path(redactor(str(session_file))),
            "malformed_lines": malformed_lines,
        },
    }


def _update_state(
    state: dict[str, Any], processed_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    if not processed_rows:
        return state

    updated = dict(state)
    updated_at_values = [
        str(row.get("updated_at", ""))
        for row in processed_rows
        if row.get("updated_at")
    ]
    if updated_at_values:
        updated["last_processed_updated_at"] = max(updated_at_values)

    existing_ids = [str(item) for item in updated.get("processed_session_ids", [])]
    merged_ids = [
        *existing_ids,
        *[str(row.get("id")) for row in processed_rows if row.get("id")],
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for session_id in reversed(merged_ids):
        if session_id in seen:
            continue
        seen.add(session_id)
        deduped.append(session_id)
    deduped.reverse()
    updated["processed_session_ids"] = deduped[-MAX_PROCESSED_SESSION_IDS:]
    return updated


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync interactive Codex sessions to W&B Weave traces"
    )
    parser.add_argument("--entity", default=DEFAULT_ENTITY, help="W&B entity/team")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="W&B project")
    parser.add_argument(
        "--once", action="store_true", help="Run one sync pass and exit"
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help="Polling interval for continuous mode",
    )
    parser.add_argument(
        "--quiet-seconds",
        type=int,
        default=DEFAULT_QUIET_SECONDS,
        help="Only sync sessions whose index updated_at is older than this",
    )
    parser.add_argument(
        "--session-root",
        default=str(DEFAULT_SESSION_ROOT),
        help="Path to Codex session files root",
    )
    parser.add_argument(
        "--index-file",
        default=str(DEFAULT_INDEX_FILE),
        help="Path to session_index.jsonl",
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="Path to sync checkpoint state JSON",
    )
    parser.add_argument(
        "--redact-regex",
        action="append",
        default=[],
        help="Additional redaction regex patterns (repeatable)",
    )
    parser.add_argument(
        "--no-redaction",
        action="store_true",
        help="Disable redaction (not recommended)",
    )
    return parser


def _run_sync_once(
    *,
    session_root: pathlib.Path,
    index_file: pathlib.Path,
    state_file: pathlib.Path,
    quiet_seconds: int,
    redactor: Callable[[Any], Any],
    redaction_enabled: bool,
) -> dict[str, Any]:
    index_rows = load_session_index(index_file)
    state = load_sync_state(state_file)
    selected_rows = select_sessions_to_process(
        index_rows=index_rows,
        state=state,
        quiet_seconds=quiet_seconds,
    )

    @weave.op()
    def ingest_interactive_session_traced(
        trace_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return trace_payload

    uploaded = 0
    skipped_missing = 0
    processed_rows: list[dict[str, Any]] = []

    for row in selected_rows:
        session_id = str(row["id"])
        session_file = find_session_file(session_root, session_id)
        if not session_file:
            skipped_missing += 1
            logger.warning(
                "Skipping missing session file: session_id=%s session_root=%s",
                session_id,
                session_root,
            )
            continue

        trace_payload = build_interactive_trace(
            session_file=session_file,
            thread_name=str(row.get("thread_name", "")),
            redactor=redactor,
            redaction_enabled=redaction_enabled,
        )
        ingest_interactive_session_traced(trace_payload)
        uploaded += 1
        processed_rows.append(row)

    updated_state = _update_state(state, processed_rows)
    save_sync_state(state_file, updated_state)

    return {
        "selected": len(selected_rows),
        "uploaded": uploaded,
        "skipped_missing": skipped_missing,
        "state_file": str(state_file),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not ensure_wandb_api_key():
        print("WANDB_API_KEY is required to sync interactive traces.", file=sys.stderr)
        return 2

    weave.init(f"{args.entity}/{args.project}")

    session_root = pathlib.Path(args.session_root).expanduser().resolve()
    index_file = pathlib.Path(args.index_file).expanduser().resolve()
    state_file = pathlib.Path(args.state_file).expanduser().resolve()
    redactor = build_redactor(args.redact_regex, enabled=not args.no_redaction)

    try:
        if args.once:
            summary = _run_sync_once(
                session_root=session_root,
                index_file=index_file,
                state_file=state_file,
                quiet_seconds=args.quiet_seconds,
                redactor=redactor,
                redaction_enabled=not args.no_redaction,
            )
            print(json.dumps(summary, ensure_ascii=True))
            return 0

        while True:
            summary = _run_sync_once(
                session_root=session_root,
                index_file=index_file,
                state_file=state_file,
                quiet_seconds=args.quiet_seconds,
                redactor=redactor,
                redaction_enabled=not args.no_redaction,
            )
            print(json.dumps(summary, ensure_ascii=True))
            time.sleep(max(1, args.poll_seconds))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"interactive sync failed: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
