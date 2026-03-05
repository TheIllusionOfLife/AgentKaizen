from __future__ import annotations

from typing import Any


def score_contains_all(output: str, must_contain: list[str]) -> dict[str, Any]:
    missing = [needle for needle in must_contain if needle not in output]
    return {
        "pass": len(missing) == 0,
        "missing": missing,
        "missing_count": len(missing),
    }


def score_forbidden_absent(output: str, must_not_contain: list[str]) -> dict[str, Any]:
    present = [needle for needle in must_not_contain if needle in output]
    return {
        "pass": len(present) == 0,
        "present": present,
        "present_count": len(present),
    }


def score_max_chars(output: str, max_chars: int | None) -> dict[str, Any]:
    length = len(output)
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


def evaluate_output(
    output: str,
    must_contain: list[str],
    must_not_contain: list[str],
    max_chars: int | None,
) -> dict[str, Any]:
    contains_result = score_contains_all(output, must_contain)
    forbidden_result = score_forbidden_absent(output, must_not_contain)
    max_chars_result = score_max_chars(output, max_chars)
    overall_pass = (
        contains_result["pass"]
        and forbidden_result["pass"]
        and max_chars_result["pass"]
    )
    return {
        "pass": overall_pass,
        "score_contains_all": contains_result,
        "score_forbidden_absent": forbidden_result,
        "score_max_chars": max_chars_result,
    }
