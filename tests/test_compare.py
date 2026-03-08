"""Tests for comparison rendering and inline case/variant building in evals."""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import agentkaizen.evals as codex_evals


def test_parse_edit_flag_handles_text_with_colons():
    result = codex_evals._parse_edit_flag("AGENTS.md:append:text with: colons")

    assert result["path"] == "AGENTS.md"
    assert result["mode"] == "append"
    assert result["text"] == "text with: colons"


def test_parse_edit_flag_rejects_missing_mode():
    try:
        codex_evals._parse_edit_flag("AGENTS.md")
    except argparse.ArgumentTypeError as exc:
        assert "PATH:MODE" in str(exc)
    else:
        raise AssertionError("Expected ArgumentTypeError")


def test_parse_edit_flag_rejects_invalid_mode():
    try:
        codex_evals._parse_edit_flag("AGENTS.md:bad_mode:some text")
    except argparse.ArgumentTypeError as exc:
        assert "bad_mode" in str(exc)
        assert "append" in str(exc)
    else:
        raise AssertionError("Expected ArgumentTypeError")


def test_build_inline_cases_groups_must_contain_to_preceding_prompt():
    argv = [
        "--prompt",
        "First question",
        "--must-contain",
        "answer1",
        "--must-contain",
        "answer2",
        "--prompt",
        "Second question",
        "--must-contain",
        "answer3",
        "--max-chars",
        "100",
    ]

    cases = codex_evals._build_inline_cases(argv)

    assert len(cases) == 2
    assert cases[0]["prompt"] == "First question"
    assert "answer1" in cases[0]["must_contain"]
    assert "answer2" in cases[0]["must_contain"]
    assert cases[1]["prompt"] == "Second question"
    assert "answer3" in cases[1]["must_contain"]
    assert cases[1]["max_chars"] == 100


def test_build_inline_cases_empty_argv_returns_empty():
    assert codex_evals._build_inline_cases([]) == []


def test_render_per_case_comparison_contains_prompts_and_outputs():
    variant_names = ["baseline", "japanese"]
    per_case_by_variant = {
        "baseline": [
            {
                "output": "This repo does things in English.",
                "scorer_results": {"score_contains_all": {"pass": True}},
            }
        ],
        "japanese": [
            {
                "output": "このリポジトリは日本語で応答します。",
                "scorer_results": {"score_contains_all": {"pass": False}},
            }
        ],
    }
    cases = [{"prompt": "What does this repo do?"}]

    rendered = codex_evals.render_per_case_comparison(
        variant_names, per_case_by_variant, cases
    )

    assert "What does this repo do?" in rendered
    assert "English" in rendered
    assert "このリポジトリ" in rendered
    assert "BASELINE" in rendered
    assert "VARIANT: japanese" in rendered
