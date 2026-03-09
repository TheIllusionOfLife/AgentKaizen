"""Sync interactive Codex sessions to W&B Weave traces."""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import re
import shlex
import sys
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from agentkaizen._trace_log import append_trace
from agentkaizen._weave_compat import HAS_WEAVE, weave_init, weave_op
from agentkaizen.core import (
    _sanitize_path,
    apply_builtin_pii_redaction,
    configure_weave_pii_redaction,
    ensure_wandb_api_key,
    resolve_weave_project,
)

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ROOT = pathlib.Path("~/.codex/sessions").expanduser()
DEFAULT_INDEX_FILE = pathlib.Path("~/.codex/session_index.jsonl").expanduser()
DEFAULT_STATE_FILE = pathlib.Path("~/.codex/weave_sync_state.json").expanduser()
DEFAULT_POLL_SECONDS = 15
DEFAULT_QUIET_SECONDS = 30
MAX_PROCESSED_SESSION_IDS = 10_000
PARSER_VERSION = 1
SUMMARY_TEXT_LIMIT = 600

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


def _flatten_message_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    if value is None:
        return ""
    return str(value)


def _sanitize_image_url(url: str) -> str:
    """Sanitize file:// URIs to avoid leaking absolute local paths."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        local_path = urllib.parse.unquote(parsed.path)
        sanitized = _sanitize_path(local_path)
        encoded = urllib.parse.quote(sanitized, safe="/[]")
        return urllib.parse.urlunparse(parsed._replace(path=encoded))
    return url


def _normalize_content_blocks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"type": "input_text", "text": value}]
    if not isinstance(value, list):
        if value is None:
            return []
        return [{"type": "input_text", "text": str(value)}]

    blocks: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            block_type = str(item.get("type") or "input_text")
            normalized: dict[str, Any] = {"type": block_type}
            if "text" in item and item.get("text") is not None:
                normalized["text"] = str(item.get("text"))
            if "image_url" in item and item.get("image_url") is not None:
                normalized["image_url"] = _sanitize_image_url(
                    str(item.get("image_url"))
                )
            if "image_path" in item and item.get("image_path") is not None:
                normalized["image_path"] = pathlib.Path(
                    str(item.get("image_path"))
                ).name
            blocks.append(normalized)
        else:
            blocks.append({"type": "input_text", "text": str(item)})
    return blocks


def _modalities_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    modalities: list[str] = []
    for message in messages:
        blocks = message.get("content_blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", ""))
            modality = "image" if "image" in block_type else "text"
            if modality not in seen:
                seen.add(modality)
                modalities.append(modality)
    return modalities


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def _truncate_text(text: str, limit: int = SUMMARY_TEXT_LIMIT) -> str:
    normalized = _normalize_whitespace(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _is_instruction_boilerplate(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if not normalized:
        return True
    lowered = normalized.lower()
    return (
        lowered.startswith("# agents.md instructions for ")
        or "<instructions>" in lowered
        or "<environment_context>" in lowered
        or "<permissions instructions>" in lowered
        or "meta-instructions" in lowered
    )


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
        if session_id in processed_ids:
            continue
        if last_processed and updated_at < str(last_processed):
            continue
        try:
            updated_dt = parse_iso8601(updated_at)
        except ValueError:
            continue
        if updated_dt > quiet_cutoff:
            continue
        selected.append(row)
    return selected


def recover_orphaned_sessions(
    *,
    session_root: pathlib.Path,
    indexed_session_ids: set[str],
    state: dict[str, Any],
    now: datetime | None = None,
    quiet_seconds: int = DEFAULT_QUIET_SECONDS,
) -> list[dict[str, Any]]:
    now_dt = now or datetime.now(UTC)
    quiet_cutoff = now_dt - timedelta(seconds=quiet_seconds)
    processed_ids = set(state.get("processed_session_ids", []))
    watermark_raw = state.get("last_processed_updated_at")
    watermark_dt: datetime | None = None
    if watermark_raw:
        try:
            watermark_dt = parse_iso8601(str(watermark_raw))
        except ValueError:
            pass
    recovered: list[dict[str, Any]] = []

    for session_file in sorted(session_root.rglob("*.jsonl")):
        session_id = ""
        updated_at = ""
        thread_name = ""
        complete = False
        try:
            raw_lines = session_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}

            if record.get("type") == "session_meta":
                session_id = _as_string(payload.get("id") or session_id)
            elif (
                record.get("type") == "response_item"
                and payload.get("type") == "message"
                and not thread_name
                and _as_string(payload.get("role")) == "user"
            ):
                thread_name = _flatten_message_content(payload.get("content"))
            elif (
                record.get("type") == "event_msg"
                and payload.get("type") == "user_message"
                and not thread_name
            ):
                thread_name = _as_string(payload.get("message") or payload.get("text"))
            elif (
                record.get("type") == "event_msg"
                and payload.get("type") == "task_complete"
            ):
                complete = True
                updated_at = _as_string(record.get("timestamp"))

        if (
            not session_id
            or session_id in indexed_session_ids
            or session_id in processed_ids
        ):
            continue
        if not complete or not updated_at:
            continue
        try:
            updated_dt = parse_iso8601(updated_at)
        except ValueError:
            continue
        if updated_dt > quiet_cutoff:
            continue
        if watermark_dt and updated_dt <= watermark_dt:
            continue
        recovered.append(
            {
                "id": session_id,
                "thread_name": thread_name or session_id,
                "updated_at": updated_at,
                "discovery_source": "recovered",
                "index_present": False,
                "session_file": str(session_file),
            }
        )
    return recovered


def collect_sessions_to_process(
    *,
    session_root: pathlib.Path,
    index_rows: list[dict[str, Any]],
    state: dict[str, Any],
    now: datetime | None = None,
    quiet_seconds: int = DEFAULT_QUIET_SECONDS,
    recover_orphans: bool = True,
) -> list[dict[str, Any]]:
    selected = select_sessions_to_process(
        index_rows=index_rows,
        state=state,
        now=now,
        quiet_seconds=quiet_seconds,
    )
    merged: dict[str, dict[str, Any]] = {
        str(row["id"]): {
            **row,
            "discovery_source": "index",
            "index_present": True,
        }
        for row in selected
    }
    if recover_orphans:
        indexed_session_ids = {
            str(row.get("id", "")) for row in index_rows if row.get("id")
        }
        for row in recover_orphaned_sessions(
            session_root=session_root,
            indexed_session_ids=indexed_session_ids,
            state=state,
            now=now,
            quiet_seconds=quiet_seconds,
        ):
            merged.setdefault(str(row["id"]), row)
    return sorted(merged.values(), key=lambda row: str(row.get("updated_at", "")))


def build_redactor(
    extra_patterns: list[str], enabled: bool = True
) -> Callable[[Any], Any]:
    if not enabled:
        return lambda value: value

    compiled = [(re.compile(pattern), True) for pattern in DEFAULT_REDACT_PATTERNS] + [
        (re.compile(pattern), False) for pattern in extra_patterns
    ]

    def redact_text(text: str) -> str:
        redacted = text
        for pattern, is_builtin in compiled:
            replacement = (
                r"\1[REDACTED]" if is_builtin and pattern.groups >= 1 else "[REDACTED]"
            )
            redacted = pattern.sub(replacement, redacted)
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


def _load_tool_command(tool_call: dict[str, Any]) -> str:
    name = tool_call.get("name", "")
    if name not in ("exec_command", "Bash"):
        return ""
    arguments = tool_call.get("arguments")
    if not isinstance(arguments, str):
        return ""
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if isinstance(payload, dict):
        return _as_string(payload.get("cmd") or payload.get("command", ""))
    return ""


def _load_tool_output(tool_call: dict[str, Any]) -> dict[str, Any]:
    if tool_call.get("name") != "function_call_output":
        return {}
    raw_output = tool_call.get("output")
    if isinstance(raw_output, dict):
        return raw_output
    if not isinstance(raw_output, str):
        return {}
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _message_is_clarification(
    assistant_message: dict[str, Any], next_message: dict[str, Any] | None
) -> bool:
    if assistant_message.get("phase") == "commentary":
        return False
    content = _normalize_whitespace(_as_string(assistant_message.get("content")))
    if "?" not in content:
        return False
    lowered = content.lower()
    clarification_patterns = (
        "should i ",
        "would you like",
        "do you want",
        "which ",
        "can you confirm",
        "could you confirm",
        "what should",
        "how should",
    )
    if not any(pattern in lowered for pattern in clarification_patterns):
        return False
    if not next_message or next_message.get("role") != "user":
        return False
    next_content = _normalize_whitespace(
        _as_string(next_message.get("content"))
    ).lower()
    if not next_content:
        return False
    return any(
        next_content.startswith(prefix)
        for prefix in (
            "yes",
            "no",
            "please",
            "use ",
            "go ",
            "run ",
            "do ",
            "the ",
            "this ",
            "that ",
        )
    )


def _message_is_user_correction(
    user_message: dict[str, Any], previous_message: dict[str, Any] | None
) -> bool:
    if user_message.get("role") != "user" or not previous_message:
        return False
    if previous_message.get("role") != "assistant":
        return False
    content = _normalize_whitespace(_as_string(user_message.get("content"))).lower()
    if not content:
        return False
    correction_prefixes = (
        "actually",
        "no,",
        "not quite",
        "you missed",
        "i meant",
        "instead",
        "rather",
    )
    if content.startswith(correction_prefixes):
        return True
    correction_markers = (
        "that's not",
        "that is not",
        "please don't",
        "didn't",
        "don't do",
        "don't update",
        "you should have",
    )
    return any(marker in content for marker in correction_markers)


def _categorize_command(command: str) -> str:
    lowered = command.lower()
    tokens: list[str]
    try:
        tokens = shlex.split(lowered)
    except ValueError:
        tokens = lowered.split()
    if "pytest" in lowered or "unittest" in lowered:
        return "test"
    if "ruff format" in lowered or "format" in tokens:
        return "format"
    if "ruff check" in lowered or "lint" in tokens:
        return "lint"
    if lowered.startswith("git ") or lowered == "git":
        return "git"
    if lowered.startswith("uv ") or lowered == "uv":
        return "uv"
    if any(token in tokens for token in ("rg", "grep", "find", "ls", "cat", "sed")):
        return "inspect"
    return "other"


def _has_completion_language(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    content = _normalize_whitespace(_as_string(message.get("content"))).lower()
    if not content:
        return False
    completion_markers = (
        "done",
        "completed",
        "finished",
        "implemented",
        "updated",
        "fixed",
        "pushed",
        "created the pr",
        "opened the pr",
    )
    return any(marker in content for marker in completion_markers)


def _build_interactive_analysis(
    *, messages: list[dict[str, Any]], tool_calls: list[dict[str, Any]], status: str
) -> dict[str, Any]:
    assistant_messages = [msg for msg in messages if msg.get("role") == "assistant"]
    user_messages = [msg for msg in messages if msg.get("role") == "user"]
    commentary_count = sum(1 for msg in messages if msg.get("phase") == "commentary")
    invocation_calls = [
        call for call in tool_calls if call.get("name") != "function_call_output"
    ]
    commands = [_load_tool_command(call) for call in invocation_calls]
    commands = [cmd for cmd in commands if cmd]

    def _contains_any(text: str, needles: list[str]) -> bool:
        lowered = text.lower()
        return any(needle in lowered for needle in needles)

    def _safe_split(text: str) -> list[str]:
        try:
            return shlex.split(text)
        except ValueError:
            return []

    user_correction_count = sum(
        1
        for index, msg in enumerate(messages)
        if msg.get("role") == "user"
        and _message_is_user_correction(msg, messages[index - 1] if index > 0 else None)
    )
    clarification_question_count = sum(
        1
        for index, msg in enumerate(messages)
        if msg.get("role") == "assistant"
        and _message_is_clarification(
            msg,
            messages[index + 1] if index + 1 < len(messages) else None,
        )
    )
    branch_created = any(
        "git checkout -b" in cmd or "git switch -c" in cmd for cmd in commands
    )
    used_uv = any("uv " in cmd or cmd.startswith("uv") for cmd in commands)
    ran_tests = any("pytest" in cmd or "unittest" in cmd for cmd in commands)
    ran_lint = any(
        "ruff check" in cmd or "lint" in _safe_split(cmd) for cmd in commands
    )
    ran_format = any(
        "ruff format" in cmd or "format" in _safe_split(cmd) for cmd in commands
    )
    command_categories: dict[str, int] = {}
    for cmd in commands:
        category = _categorize_command(cmd)
        command_categories[category] = command_categories.get(category, 0) + 1
    used_skills = any("SKILL.md" in _as_string(msg.get("content")) for msg in messages)
    error_count = sum(
        1
        for call in tool_calls
        if (
            (payload := _load_tool_output(call))
            and (
                int(payload.get("exit_code") or 0) != 0
                or int(payload.get("returncode") or 0) != 0
                or bool(payload.get("error"))
                or bool(payload.get("exception"))
            )
        )
    )
    if status == "complete":
        completion_signal_source = "task_complete_event"
    elif assistant_messages and _has_completion_language(assistant_messages[-1]):
        completion_signal_source = "assistant_response_only"
    else:
        completion_signal_source = "incomplete"

    return {
        "user_turn_count": len(user_messages),
        "assistant_turn_count": len(assistant_messages),
        "commentary_count": commentary_count,
        "tool_call_count": len(invocation_calls),
        "web_search_count": 0,
        "error_count": error_count,
        "tool_error_count": error_count,
        "task_completed": status == "complete",
        "completion_signal_source": completion_signal_source,
        "branch_created": branch_created,
        "used_uv": used_uv,
        "ran_tests": ran_tests,
        "ran_lint": ran_lint,
        "ran_format": ran_format,
        "command_categories": command_categories,
        "used_skills": used_skills,
        "clarification_question_count": clarification_question_count,
        "user_correction_count": user_correction_count,
    }


def _derive_user_task(
    thread_name: str, messages: list[dict[str, Any]]
) -> tuple[str, str]:
    seen: set[str] = set()
    for msg in messages:
        if msg.get("role") != "user":
            continue
        raw_content = _as_string(msg.get("content"))
        normalized = _normalize_whitespace(raw_content)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if _is_instruction_boilerplate(normalized):
            continue
        return normalized, "messages"
    return _normalize_whitespace(thread_name), "thread_name"


def _build_analysis_summary(
    *,
    thread_name: str,
    user_task: str,
    messages: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> str:
    last_assistant = next(
        (
            _as_string(msg.get("content"))
            for msg in reversed(messages)
            if msg.get("role") == "assistant"
        ),
        "",
    )
    return (
        f"Thread: {thread_name}\n"
        f"User request: {_truncate_text(user_task)}\n"
        f"Completed: {analysis['task_completed']}\n"
        f"Tool calls: {analysis['tool_call_count']}\n"
        f"Workflow: branch={analysis['branch_created']} uv={analysis['used_uv']} tests={analysis['ran_tests']}\n"
        f"User corrections: {analysis['user_correction_count']}\n"
        f"Final assistant message: {_truncate_text(last_assistant)}"
    )


def build_interactive_trace(
    *,
    session_file: pathlib.Path,
    thread_name: str,
    redactor: Callable[[Any], Any],
    redaction_enabled: bool = True,
    discovery_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safe_thread_name = _as_string(redactor(thread_name))
    messages: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    session_meta: dict[str, Any] = {}
    token_usage: dict[str, Any] = {}
    malformed_lines = 0
    complete = False
    completed_at = ""

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
                content_blocks = redactor(
                    _normalize_content_blocks(payload.get("content"))
                )
                messages.append(
                    {
                        "timestamp": ts,
                        "role": _as_string(payload.get("role")),
                        "content": redactor(
                            _flatten_message_content(payload.get("content"))
                        ),
                        "content_blocks": content_blocks,
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
                if maybe_text is None:
                    maybe_text = payload.get("message")
                if maybe_text is not None:
                    messages.append(
                        {
                            "timestamp": ts,
                            "role": "user"
                            if payload_type == "user_message"
                            else "assistant",
                            "content": redactor(_as_string(maybe_text)),
                            "content_blocks": redactor(
                                [{"type": "input_text", "text": _as_string(maybe_text)}]
                            ),
                            "phase": _as_string(payload.get("phase")),
                            "source": "event_msg",
                        }
                    )
            elif payload_type == "task_complete":
                complete = True
                completed_at = ts

    status = "complete" if complete else "partial"
    if malformed_lines > 0 and not messages and not tool_calls:
        status = "parse_error"
    analysis = _build_interactive_analysis(
        messages=messages,
        tool_calls=tool_calls,
        status=status,
    )
    user_task, user_task_source = _derive_user_task(safe_thread_name, messages)
    resolved_thread_name = safe_thread_name or user_task
    modalities = _modalities_from_messages(messages)
    updated_at = (
        _as_string((discovery_metadata or {}).get("updated_at")) or completed_at
    )

    trace_payload = {
        "source": "codex_interactive",
        "session_id": _as_string(session_meta.get("id") or session_file.stem),
        "thread_name": resolved_thread_name,
        "user_task": user_task,
        "cwd": _sanitize_path(redactor(_as_string(session_meta.get("cwd")))),
        "cli_version": _as_string(session_meta.get("cli_version")),
        "started_at": _as_string(session_meta.get("timestamp")),
        "completed_at": completed_at,
        "updated_at": updated_at,
        "status": status,
        "modalities": modalities,
        "messages": messages,
        "tool_calls": tool_calls,
        "token_usage": token_usage,
        "analysis": analysis,
        "analysis_summary": _build_analysis_summary(
            thread_name=resolved_thread_name,
            user_task=user_task,
            messages=messages,
            analysis=analysis,
        ),
        "ingest_metadata": {
            "parser_version": PARSER_VERSION,
            "redaction_enabled": redaction_enabled,
            "session_file": _sanitize_path(redactor(str(session_file))),
            "malformed_lines": malformed_lines,
            "user_task_source": user_task_source,
            **(discovery_metadata or {}),
        },
    }
    return apply_builtin_pii_redaction(trace_payload, enabled=redaction_enabled)


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
    parser.add_argument("--entity", help="W&B entity/team")
    parser.add_argument("--project", help="W&B project")
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
    parser.add_argument(
        "--no-recover-orphans",
        action="store_true",
        help="Disable fallback scanning for completed session files missing from the index",
    )
    parser.add_argument(
        "--agent",
        default=None,
        choices=["codex", "claude-code"],
        help="Agent type for session sync (default: from config, then codex)",
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
    recover_orphans: bool = True,
) -> dict[str, Any]:
    index_rows = load_session_index(index_file)
    state = load_sync_state(state_file)
    if not state.get("last_processed_updated_at") and not state.get(
        "processed_session_ids"
    ):
        seeded_state = dict(state)
        if index_rows:
            seeded_state["last_processed_updated_at"] = str(
                index_rows[-1].get("updated_at", "")
            )
        save_sync_state(state_file, seeded_state)
        return {
            "selected": 0,
            "uploaded": 0,
            "skipped_missing": 0,
            "state_file": str(state_file),
        }
    selected_rows = collect_sessions_to_process(
        session_root=session_root,
        index_rows=index_rows,
        state=state,
        quiet_seconds=quiet_seconds,
        recover_orphans=recover_orphans,
    )

    @weave_op()
    def ingest_interactive_session_traced(
        trace_payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            append_trace(trace_payload, op_name="ingest_interactive_session_traced")
        except Exception as exc:
            print(f"warning: failed to write local trace: {exc}", file=sys.stderr)
        return trace_payload

    uploaded = 0
    skipped_missing = 0
    processed_rows: list[dict[str, Any]] = []

    for row in selected_rows:
        session_id = str(row["id"])
        session_file = (
            pathlib.Path(str(row["session_file"])).resolve()
            if row.get("session_file")
            else find_session_file(session_root, session_id)
        )
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
            discovery_metadata={
                "discovery_source": str(row.get("discovery_source", "index")),
                "index_present": bool(row.get("index_present", True)),
                "updated_at": str(row.get("updated_at", "")),
            },
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
    from agentkaizen.config import load_config, merge_cli_args

    parser = _build_parser()
    args = parser.parse_args(argv)

    config = load_config()
    config = merge_cli_args(config, args)

    tracing_enabled = HAS_WEAVE and bool(ensure_wandb_api_key())
    if tracing_enabled:
        try:
            project_path = resolve_weave_project(config.entity, config.project)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        if not HAS_WEAVE:
            print(
                "info: weave not installed — running in local-only mode.",
                file=sys.stderr,
            )
        elif not ensure_wandb_api_key():
            print(
                "info: WANDB_API_KEY not set — running in local-only mode.",
                file=sys.stderr,
            )

    if config.agent == "claude-code":
        from agentkaizen.claude_code_session import sync_claude_sessions

        # Forward W&B settings from merged config into args so sync_claude_sessions
        # sees entity/project even when set only in pyproject.toml or env vars.
        if not getattr(args, "entity", None):
            args.entity = config.entity
        if not getattr(args, "project", None):
            args.project = config.project
        return sync_claude_sessions(args)

    configure_weave_pii_redaction(enabled=not args.no_redaction)
    if tracing_enabled:
        weave_init(project_path)

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
                recover_orphans=not args.no_recover_orphans,
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
                recover_orphans=not args.no_recover_orphans,
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
