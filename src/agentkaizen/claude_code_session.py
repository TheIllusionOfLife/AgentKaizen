"""Parse and sync Claude Code interactive sessions from ~/.claude/projects/."""

from __future__ import annotations

import json
import pathlib
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from agentkaizen._trace_log import append_trace
from agentkaizen._weave_compat import weave_op
from agentkaizen.core import _sanitize_path, apply_builtin_pii_redaction
from agentkaizen.session_sync import (
    DEFAULT_QUIET_SECONDS,
    PARSER_VERSION,
    _as_string,
    _build_analysis_summary,
    _build_interactive_analysis,
    _derive_user_task,
    _is_instruction_boilerplate,
    build_redactor,
    load_sync_state,
    save_sync_state,
)

DEFAULT_CLAUDE_SESSION_ROOT = pathlib.Path("~/.claude/projects").expanduser()
DEFAULT_CLAUDE_STATE_FILE = pathlib.Path(
    "~/.agentkaizen/claude_code_sync_state.json"
).expanduser()
DEFAULT_POLL_SECONDS = 15

# Record types to skip entirely — high-volume metadata with no analysis value.
_SKIP_RECORD_TYPES = frozenset(
    {
        "progress",
        "system",
        "file-history-snapshot",
        "queue-operation",
    }
)


def discover_claude_sessions(
    session_root: pathlib.Path,
    *,
    project_slug: str | None = None,
) -> list[dict[str, Any]]:
    """Return metadata dicts for Claude Code JSONL session files.

    Files under ``*/subagents/`` directories are excluded. Symlinks are skipped
    for security. Paths are resolved and verified to be inside ``session_root``.
    """
    if not session_root.exists():
        return []

    resolved_root = session_root.resolve()
    search_root = resolved_root / project_slug if project_slug else resolved_root

    sessions: list[dict[str, Any]] = []
    for candidate in sorted(search_root.rglob("*.jsonl")):
        # Skip symlinks (security: don't follow out-of-tree links).
        if candidate.is_symlink():
            continue
        # Resolve and confirm the file is inside session_root.
        try:
            resolved = candidate.resolve()
            resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        # Skip subagent session files.
        if "subagents" in resolved.parts:
            continue

        meta = _read_session_metadata(resolved)
        sessions.append(
            {
                "path": resolved,
                "session_id": meta.get("session_id", resolved.stem),
                "cwd": meta.get("cwd", ""),
                "git_branch": meta.get("git_branch", ""),
                "version": meta.get("version", ""),
                "started_at": meta.get("started_at", ""),
                "completed_at": meta.get("completed_at", ""),
            }
        )

    return sessions


def _read_session_metadata(path: pathlib.Path) -> dict[str, Any]:
    """Extract lightweight metadata from the first and last records of a session file."""
    meta: dict[str, Any] = {}
    lines: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
    except OSError:
        return meta

    # Read first useful record for session metadata.
    for raw in lines[:20]:
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if not meta.get("session_id") and record.get("sessionId"):
            meta["session_id"] = str(record["sessionId"])
        if not meta.get("cwd") and record.get("cwd"):
            meta["cwd"] = str(record["cwd"])
        if not meta.get("git_branch") and record.get("gitBranch"):
            meta["git_branch"] = str(record["gitBranch"])
        if not meta.get("version") and record.get("version"):
            meta["version"] = str(record["version"])
        if not meta.get("started_at") and record.get("timestamp"):
            meta["started_at"] = str(record["timestamp"])
        if meta.get("session_id"):
            break

    # Use file mtime as completed_at approximation.
    try:
        mtime = path.stat().st_mtime
        meta["completed_at"] = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    except OSError:
        pass

    # Try to find timestamp of the last record.
    for raw in reversed(lines[-10:]):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("timestamp"):
            meta["completed_at"] = str(record["timestamp"])
            break

    return meta


def build_claude_code_trace(
    session_path: pathlib.Path,
    *,
    redactor: Callable[[Any], Any] | None = None,
    redaction_enabled: bool = True,
) -> dict[str, Any]:
    """Parse a Claude Code session JSONL file into a trace dict.

    Streams line-by-line to handle large sessions. Uses errors='replace' for
    non-UTF8 fragments.
    """
    if redactor is None:
        redactor = build_redactor([], enabled=redaction_enabled)

    messages: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    session_id = session_path.stem
    cwd = ""
    git_branch = ""
    cli_version = ""
    started_at = ""
    has_last_prompt = False
    last_assistant_stop_reason: str | None = None
    last_timestamp = ""

    # Accumulate token usage across all assistant records.
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation = 0
    total_cache_read = 0
    malformed_lines = 0

    try:
        fh = session_path.open(encoding="utf-8", errors="replace")
    except OSError:
        return _empty_trace(session_path, redaction_enabled)

    with fh:
        for raw_line in fh:
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

            record_type = str(record.get("type", ""))
            ts = _as_string(record.get("timestamp", ""))
            if ts:
                last_timestamp = ts

            # Seed session metadata from first records.
            if not session_id or session_id == session_path.stem:
                if record.get("sessionId"):
                    session_id = str(record["sessionId"])
            if not cwd and record.get("cwd"):
                cwd = str(record["cwd"])
            if not git_branch and record.get("gitBranch"):
                git_branch = str(record["gitBranch"])
            if not cli_version and record.get("version"):
                cli_version = str(record["version"])
            if not started_at and ts:
                started_at = ts

            if record_type in _SKIP_RECORD_TYPES:
                continue

            if record_type == "last-prompt":
                has_last_prompt = True
                continue

            if record_type == "user":
                _process_user_record(record, ts, redactor, messages, tool_calls)

            elif record_type == "assistant":
                stop_reason = _process_assistant_record(
                    record, ts, redactor, messages, tool_calls
                )
                if stop_reason is not None:
                    last_assistant_stop_reason = stop_reason
                # Accumulate token usage.
                usage = record.get("message", {}).get("usage") or {}
                if isinstance(usage, dict):
                    total_input_tokens += int(usage.get("input_tokens") or 0)
                    total_output_tokens += int(usage.get("output_tokens") or 0)
                    total_cache_creation += int(
                        usage.get("cache_creation_input_tokens") or 0
                    )
                    total_cache_read += int(usage.get("cache_read_input_tokens") or 0)

    # Determine completion status.
    if last_assistant_stop_reason == "end_turn":
        status = "complete"
        status_reason = "end_turn"
    elif has_last_prompt:
        status = "complete"
        status_reason = "last_prompt"
    else:
        status = "incomplete"
        status_reason = "no_signal"

    token_usage = {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "total_tokens": total_input_tokens + total_output_tokens,
        "cache_creation_input_tokens": total_cache_creation,
        "cache_read_input_tokens": total_cache_read,
    }

    analysis = _build_interactive_analysis(
        messages=messages,
        tool_calls=tool_calls,
        status=status,
    )

    # Derive thread_name from slug (directory name) or first user message.
    slug = session_path.parent.name
    user_task, user_task_source = _derive_user_task(slug, messages)
    thread_name = slug or user_task

    safe_thread_name = _as_string(redactor(thread_name))
    safe_user_task = _as_string(redactor(user_task))

    completed_at = last_timestamp

    trace_payload: dict[str, Any] = {
        "source": "claude_code_interactive",
        "session_id": _as_string(redactor(session_id)),
        "thread_name": safe_thread_name,
        "user_task": safe_user_task,
        "cwd": _sanitize_path(redactor(_as_string(cwd))),
        "git_branch": _as_string(redactor(git_branch)),
        "cli_version": _as_string(redactor(cli_version)),
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "status_reason": status_reason,
        "messages": messages,
        "tool_calls": tool_calls,
        "token_usage": token_usage,
        "analysis": analysis,
        "analysis_summary": _build_analysis_summary(
            thread_name=safe_thread_name,
            user_task=safe_user_task,
            messages=messages,
            analysis=analysis,
        ),
        "ingest_metadata": {
            "parser_version": PARSER_VERSION,
            "redaction_enabled": redaction_enabled,
            "session_file": _sanitize_path(redactor(str(session_path))),
            "malformed_lines": malformed_lines,
            "user_task_source": user_task_source,
        },
    }
    redacted = apply_builtin_pii_redaction(trace_payload, enabled=redaction_enabled)
    # Restore structural/enum fields that PII redactors must not modify.
    redacted["status"] = status
    redacted["status_reason"] = status_reason
    redacted["source"] = "claude_code_interactive"
    return redacted


def _process_user_record(
    record: dict[str, Any],
    ts: str,
    redactor: Callable[[Any], Any],
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    """Extract messages and tool results from a 'user' record."""
    message = record.get("message", {})
    if not isinstance(message, dict):
        return
    content = message.get("content")

    if isinstance(content, str):
        # Plain text user message.
        if not _is_instruction_boilerplate(content):
            messages.append(
                {
                    "timestamp": ts,
                    "role": "user",
                    "content": redactor(content),
                    "content_blocks": redactor(
                        [{"type": "input_text", "text": content}]
                    ),
                    "phase": "",
                    "source": "claude_code_user",
                }
            )
    elif isinstance(content, list):
        # May contain tool_result blocks and/or text blocks.
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", ""))
            if block_type == "tool_result":
                _extract_tool_result(block, ts, redactor, tool_calls)
            elif block_type == "text":
                text = str(block.get("text", ""))
                if text and not _is_instruction_boilerplate(text):
                    text_parts.append(text)
        if text_parts:
            combined = " ".join(text_parts)
            messages.append(
                {
                    "timestamp": ts,
                    "role": "user",
                    "content": redactor(combined),
                    "content_blocks": redactor(
                        [{"type": "input_text", "text": combined}]
                    ),
                    "phase": "",
                    "source": "claude_code_user",
                }
            )


def _extract_tool_result(
    block: dict[str, Any],
    ts: str,
    redactor: Callable[[Any], Any],
    tool_calls: list[dict[str, Any]],
) -> None:
    """Append a normalized function_call_output entry from a tool_result block."""
    call_id = str(block.get("tool_use_id", ""))
    raw_content = block.get("content", "")
    is_error = bool(block.get("is_error", False))

    if isinstance(raw_content, list):
        text_parts = [
            str(item.get("text", ""))
            for item in raw_content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        output_str = "\n".join(text_parts)
    else:
        output_str = str(raw_content)

    # Encode error info so _load_tool_output can detect it.
    if is_error:
        output_payload = json.dumps(
            {"error": output_str, "exit_code": 1}, ensure_ascii=True
        )
    else:
        output_payload = output_str

    tool_calls.append(
        {
            "timestamp": ts,
            "name": "function_call_output",
            "call_id": call_id,
            "output": redactor(output_payload),
        }
    )


def _process_assistant_record(
    record: dict[str, Any],
    ts: str,
    redactor: Callable[[Any], Any],
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> str | None:
    """Extract text messages and tool_use calls from an 'assistant' record.

    Returns the stop_reason string if present, else None.
    """
    message = record.get("message", {})
    if not isinstance(message, dict):
        return None

    stop_reason: str | None = message.get("stop_reason")
    content = message.get("content", [])
    if not isinstance(content, list):
        return stop_reason

    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type", ""))
        if block_type == "text":
            text = str(block.get("text", ""))
            if text:
                text_parts.append(text)
        elif block_type == "tool_use":
            tool_calls.append(
                {
                    "timestamp": ts,
                    "name": str(block.get("name", "")),
                    "call_id": str(block.get("id", "")),
                    "arguments": redactor(
                        json.dumps(block.get("input", {}), ensure_ascii=True)
                    ),
                }
            )
        # "thinking" blocks are skipped intentionally.

    if text_parts:
        combined = " ".join(text_parts)
        messages.append(
            {
                "timestamp": ts,
                "role": "assistant",
                "content": redactor(combined),
                "content_blocks": redactor([{"type": "input_text", "text": combined}]),
                "phase": "",
                "source": "claude_code_assistant",
            }
        )

    return stop_reason


def _empty_trace(session_path: pathlib.Path, redaction_enabled: bool) -> dict[str, Any]:
    return {
        "source": "claude_code_interactive",
        "session_id": session_path.stem,
        "thread_name": "",
        "user_task": "",
        "cwd": "",
        "git_branch": "",
        "cli_version": "",
        "started_at": "",
        "completed_at": "",
        "status": "parse_error",
        "status_reason": "no_signal",
        "messages": [],
        "tool_calls": [],
        "token_usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        "analysis": _build_interactive_analysis(
            messages=[], tool_calls=[], status="parse_error"
        ),
        "analysis_summary": "",
        "ingest_metadata": {
            "parser_version": PARSER_VERSION,
            "redaction_enabled": redaction_enabled,
            "session_file": str(session_path),
            "malformed_lines": 0,
            "user_task_source": "none",
        },
    }


def sync_claude_sessions(args: Any) -> int:
    """Sync Claude Code sessions; delegates from session_sync main when --agent claude-code."""
    from agentkaizen._weave_compat import HAS_WEAVE, weave_init
    from agentkaizen.core import (
        configure_weave_pii_redaction,
        ensure_wandb_api_key,
        resolve_weave_project,
    )

    tracing_enabled = HAS_WEAVE and bool(ensure_wandb_api_key())
    if tracing_enabled:
        try:
            entity = getattr(args, "entity", None)
            project = getattr(args, "project", None)
            project_path = resolve_weave_project(entity, project)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        configure_weave_pii_redaction(enabled=not getattr(args, "no_redaction", False))
        weave_init(project_path)
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

    session_root_arg = getattr(args, "session_root", None)
    session_root = (
        pathlib.Path(session_root_arg).expanduser().resolve()
        if session_root_arg
        else DEFAULT_CLAUDE_SESSION_ROOT.resolve()
    )
    state_file_arg = getattr(args, "state_file", None)
    state_file = (
        pathlib.Path(state_file_arg).expanduser().resolve()
        if state_file_arg
        else DEFAULT_CLAUDE_STATE_FILE.resolve()
    )
    quiet_seconds = int(getattr(args, "quiet_seconds", DEFAULT_QUIET_SECONDS))
    redact_regex = list(getattr(args, "redact_regex", []))
    redaction_enabled = not getattr(args, "no_redaction", False)
    redactor = build_redactor(redact_regex, enabled=redaction_enabled)

    try:
        if getattr(args, "once", False):
            summary = _run_claude_sync_once(
                session_root=session_root,
                state_file=state_file,
                quiet_seconds=quiet_seconds,
                redactor=redactor,
                redaction_enabled=redaction_enabled,
            )
            import json as _json

            print(_json.dumps(summary, ensure_ascii=True))
            return 0

        while True:
            summary = _run_claude_sync_once(
                session_root=session_root,
                state_file=state_file,
                quiet_seconds=quiet_seconds,
                redactor=redactor,
                redaction_enabled=redaction_enabled,
            )
            import json as _json

            print(_json.dumps(summary, ensure_ascii=True))
            time.sleep(max(1, int(getattr(args, "poll_seconds", DEFAULT_POLL_SECONDS))))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"claude code session sync failed: {exc}", file=sys.stderr)
        return 3


def _run_claude_sync_once(
    *,
    session_root: pathlib.Path,
    state_file: pathlib.Path,
    quiet_seconds: int,
    redactor: Callable[[Any], Any],
    redaction_enabled: bool,
) -> dict[str, Any]:
    state = load_sync_state(state_file)
    processed_paths: set[str] = set(state.get("processed_session_ids", []))

    # Seed state on first run — don't backfill entire history.
    if not state.get("last_processed_updated_at") and not processed_paths:
        sessions = discover_claude_sessions(session_root)
        seeded_state = dict(state)
        seeded_state["processed_session_ids"] = [str(s["path"]) for s in sessions]
        if sessions:
            seeded_state["last_processed_updated_at"] = sessions[-1].get(
                "completed_at", ""
            )
        save_sync_state(state_file, seeded_state)
        return {
            "selected": 0,
            "uploaded": 0,
            "seeded": len(sessions),
            "state_file": str(state_file),
        }

    sessions = discover_claude_sessions(session_root)
    now = datetime.now(UTC)
    quiet_cutoff = now - timedelta(seconds=quiet_seconds)

    to_process: list[dict[str, Any]] = []
    for session in sessions:
        path_key = str(session["path"])
        if path_key in processed_paths:
            continue
        completed_at = session.get("completed_at", "")
        if completed_at:
            try:
                completed_dt = datetime.fromisoformat(
                    completed_at.replace("Z", "+00:00")
                )
                if completed_dt > quiet_cutoff:
                    continue
            except ValueError:
                pass
        to_process.append(session)

    @weave_op()
    def ingest_claude_code_session(trace_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            append_trace(trace_payload, op_name="ingest_claude_code_session")
        except Exception as exc:
            print(f"warning: failed to write local trace: {exc}", file=sys.stderr)
        return trace_payload

    uploaded = 0
    new_processed: list[str] = []

    for session in to_process:
        trace = build_claude_code_trace(
            session["path"],
            redactor=redactor,
            redaction_enabled=redaction_enabled,
        )
        ingest_claude_code_session(trace)
        _print_session_summary(trace)
        uploaded += 1
        new_processed.append(str(session["path"]))

    updated_state = dict(state)
    existing = list(state.get("processed_session_ids", []))
    updated_state["processed_session_ids"] = (existing + new_processed)[-10_000:]
    if to_process:
        updated_state["last_processed_updated_at"] = to_process[-1].get(
            "completed_at", ""
        )
    save_sync_state(state_file, updated_state)

    return {
        "selected": len(to_process),
        "uploaded": uploaded,
        "state_file": str(state_file),
    }


def _print_session_summary(trace: dict[str, Any]) -> None:
    session_id = str(trace.get("session_id", ""))[:12]
    user_task = str(trace.get("user_task", ""))[:80] or "(no task)"
    msgs = len(trace.get("messages", []))
    tools = len(trace.get("tool_calls", []))
    usage = trace.get("token_usage", {})
    total_tokens = int(usage.get("total_tokens") or 0)
    status = str(trace.get("status", ""))
    print(
        f"  session={session_id} status={status} msgs={msgs} tools={tools}"
        f" tokens={total_tokens} task={user_task!r}"
    )
