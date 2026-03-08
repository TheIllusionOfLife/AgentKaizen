"""Local PII redaction — regex-based fallback when Weave is not installed.

Replaces ``weave.trace.settings.UserSettings`` and
``weave.utils.pii_redaction.redact_pii()`` with best-effort regex detection.

Limitation: regex patterns catch common PII formats but may miss
context-sensitive secrets or produce false positives.  When Weave is
installed, its ML-based redaction is used instead.
"""

from __future__ import annotations

import re
from typing import Any

PII_PATTERNS: list[tuple[str, str]] = [
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL_REDACTED]"),
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE_REDACTED]"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN_REDACTED]"),
    (r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", "[CARD_REDACTED]"),
    (r"(?i)(sk|pk|api[_-]?key)[_-]?[A-Za-z0-9_-]{20,}", "[API_KEY_REDACTED]"),
    (r"(?i)(bearer|token|password|secret)\s*[=:]\s*\S+", "[SECRET_REDACTED]"),
]

_compiled_patterns: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern), replacement) for pattern, replacement in PII_PATTERNS
]

_redaction_enabled: bool = False
_redaction_fields: list[str] = []


def configure_pii_redaction(
    enabled: bool = True, fields: list[str] | None = None
) -> None:
    """Configure which fields to redact — replaces ``UserSettings.apply()``."""
    global _redaction_enabled, _redaction_fields  # noqa: PLW0603
    _redaction_enabled = enabled
    _redaction_fields = list(fields) if fields else []


def _redact_string(value: str) -> str:
    """Apply all PII regex patterns to a single string."""
    result = value
    for pattern, replacement in _compiled_patterns:
        result = pattern.sub(replacement, result)
    return result


def redact_pii_local(value: dict[str, Any] | str) -> dict[str, Any] | str:
    """Apply PII redaction to *value*.

    Recursively walks dicts and applies regex patterns to string values
    found in configured fields.  If *_redaction_enabled* is ``False``,
    returns *value* unchanged.
    """
    if not _redaction_enabled:
        return value

    if isinstance(value, str):
        return _redact_string(value)

    if isinstance(value, dict):
        return _redact_dict(value, at_root=True)

    return value


def _redact_dict(d: dict[str, Any], *, at_root: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, val in d.items():
        should_redact = at_root and (not _redaction_fields or key in _redaction_fields)
        if should_redact:
            result[key] = _redact_value(val)
        elif isinstance(val, dict):
            result[key] = _redact_dict(val, at_root=False)
        else:
            result[key] = val
    return result


def _redact_value(val: Any) -> Any:
    if isinstance(val, str):
        return _redact_string(val)
    if isinstance(val, list):
        return [_redact_value(item) for item in val]
    if isinstance(val, dict):
        return {k: _redact_value(v) for k, v in val.items()}
    return val
