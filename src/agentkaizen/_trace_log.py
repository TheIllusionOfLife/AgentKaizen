"""Local JSONL trace log — replaces Weave client trace storage.

Provides ``append_trace`` and ``read_traces`` to persist and query
agent execution traces locally when Weave is not available.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TRACE_LOG = Path("~/.agentkaizen/traces.jsonl").expanduser()

TRACE_SCHEMA_VERSION = 1


def append_trace(
    payload: dict[str, Any],
    *,
    op_name: str,
    log_path: Path | None = None,
) -> None:
    """Append a trace entry to local JSONL log.

    Each entry: ``{"version": 1, "op_name": str, "started_at": ISO8601, "output": dict}``
    Creates parent directory if needed.
    Uses atomic write (write to temp file, then rename) to prevent
    corruption from concurrent processes.
    """
    target = log_path or DEFAULT_TRACE_LOG
    target.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "version": TRACE_SCHEMA_VERSION,
        "op_name": op_name,
        "started_at": datetime.now(UTC).isoformat(),
        "output": payload,
    }
    line = json.dumps(entry, ensure_ascii=True) + "\n"

    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), prefix=".trace_", suffix=".tmp"
    )
    try:
        # Read existing content first
        existing = ""
        if target.exists():
            existing = target.read_text(encoding="utf-8")

        os.write(fd, (existing + line).encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, str(target))
    except Exception:
        os.close(fd) if not os.get_inheritable(fd) else None  # noqa: E501
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def read_traces(
    *,
    log_path: Path | None = None,
    limit: int = 100,
    op_name_substring: str | None = None,
    sort_by: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Read traces from local JSONL log with filtering and sorting.

    - Filter by op_name substring
    - Sort by field/direction (default: started_at desc)
    - Limit results
    - Tolerates malformed lines (skip with warning, don't crash)
    """
    target = log_path or DEFAULT_TRACE_LOG
    if not target.exists():
        return []

    entries: list[dict[str, Any]] = []
    for line_num, raw_line in enumerate(
        target.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed trace line %d in %s", line_num, target)
            continue
        if not isinstance(entry, dict):
            continue

        if op_name_substring and op_name_substring not in str(entry.get("op_name", "")):
            continue

        entries.append(entry)

    # Sort
    sort_rules = sort_by or [{"field": "started_at", "direction": "desc"}]
    for rule in reversed(sort_rules):
        field = rule.get("field", "started_at")
        descending = rule.get("direction", "desc") == "desc"
        entries.sort(key=lambda e: str(e.get(field, "")), reverse=descending)

    return entries[:limit]
