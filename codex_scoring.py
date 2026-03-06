from __future__ import annotations

import json
import re
from typing import Any


def _extract_text(output: str | dict[str, Any]) -> str:
    if isinstance(output, dict):
        value = output.get("text", "")
        return value if isinstance(value, str) else str(value)
    return output


def _extract_usage(output: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(output, dict):
        usage = output.get("usage", {})
        if isinstance(usage, dict):
            return usage
    return {}


def score_contains_all(
    output: str | dict[str, Any], must_contain: list[str]
) -> dict[str, Any]:
    text = _extract_text(output)
    missing = [needle for needle in must_contain if needle not in text]
    return {
        "pass": len(missing) == 0,
        "missing": missing,
        "missing_count": len(missing),
    }


def score_forbidden_absent(
    output: str | dict[str, Any], must_not_contain: list[str]
) -> dict[str, Any]:
    text = _extract_text(output)
    present = [needle for needle in must_not_contain if needle in text]
    return {
        "pass": len(present) == 0,
        "present": present,
        "present_count": len(present),
    }


def score_max_chars(
    output: str | dict[str, Any], max_chars: int | None
) -> dict[str, Any]:
    text = _extract_text(output)
    length = len(text)
    if max_chars is None:
        return {
            "pass": True,
            "length": length,
            "max_chars": None,
        }
    return {
        "pass": length <= max_chars,
        "length": length,
        "max_chars": max_chars,
    }


def score_json_validity(
    output: str | dict[str, Any], require_json: bool = False
) -> dict[str, Any]:
    if not require_json:
        return {"pass": True, "require_json": False, "valid_json": None}
    text = _extract_text(output).strip()
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return {"pass": False, "require_json": True, "valid_json": False}
    return {"pass": True, "require_json": True, "valid_json": True}


def score_required_sections(
    output: str | dict[str, Any], required_sections: list[str] | None = None
) -> dict[str, Any]:
    if not required_sections:
        return {"pass": True, "missing_sections": [], "required_count": 0}
    text = _extract_text(output)
    missing: list[str] = []
    for section in required_sections:
        pattern = re.compile(
            rf"(?im)^\s{{0,3}}(?:#+\s*)?{re.escape(section)}(?:\s*$|\s*[:\-])"
        )
        if not pattern.search(text):
            missing.append(section)
    return {
        "pass": len(missing) == 0,
        "missing_sections": missing,
        "required_count": len(required_sections),
    }


def score_file_path_citations(
    output: str | dict[str, Any], require_file_paths: bool = False
) -> dict[str, Any]:
    if not require_file_paths:
        return {"pass": True, "path_count": 0, "require_file_paths": False}
    text = _extract_text(output)
    matches = re.findall(
        r"(?:^|[\s\[(])([A-Za-z0-9_.\-]+/[A-Za-z0-9_./\-]+\.[A-Za-z0-9_]+(?:#L\d+(?:C\d+)?)?)",
        text,
    )
    return {
        "pass": len(matches) > 0,
        "path_count": len(matches),
        "require_file_paths": True,
    }


def score_token_usage(output: str | dict[str, Any]) -> dict[str, Any]:
    usage = _extract_usage(output)

    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = _safe_int(usage.get("input_tokens", 0))
    output_tokens = _safe_int(usage.get("output_tokens", 0))
    total_tokens = input_tokens + output_tokens
    return {
        "pass": True,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def evaluate_output(
    output: str | dict[str, Any],
    must_contain: list[str] | None = None,
    must_not_contain: list[str] | None = None,
    max_chars: int | None = None,
    require_json: bool = False,
    required_sections: list[str] | None = None,
    require_file_paths: bool = False,
) -> dict[str, Any]:
    contains_result = score_contains_all(output, must_contain or [])
    forbidden_result = score_forbidden_absent(output, must_not_contain or [])
    max_chars_result = score_max_chars(output, max_chars)
    json_result = score_json_validity(output, require_json=require_json)
    sections_result = score_required_sections(
        output, required_sections=required_sections
    )
    file_path_result = score_file_path_citations(
        output, require_file_paths=require_file_paths
    )
    overall_pass = (
        contains_result["pass"]
        and forbidden_result["pass"]
        and max_chars_result["pass"]
        and json_result["pass"]
        and sections_result["pass"]
        and file_path_result["pass"]
    )
    return {
        "pass": overall_pass,
        "score_contains_all": contains_result,
        "score_forbidden_absent": forbidden_result,
        "score_max_chars": max_chars_result,
        "score_json_validity": json_result,
        "score_required_sections": sections_result,
        "score_file_path_citations": file_path_result,
    }
