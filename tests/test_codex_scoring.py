import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_scoring


def test_evaluate_output_pass_case():
    result = codex_scoring.evaluate_output(
        output="hello world",
        must_contain=["hello"],
        must_not_contain=["forbidden"],
        exact_match=None,
        max_chars=20,
    )

    assert result["pass"] is True
    assert result["score_contains_all"]["pass"] is True
    assert result["score_forbidden_absent"]["pass"] is True
    assert result["score_max_chars"]["pass"] is True


def test_evaluate_output_violation_case():
    result = codex_scoring.evaluate_output(
        output="too long",
        must_contain=["missing"],
        must_not_contain=["long"],
        exact_match="ok",
        max_chars=3,
    )

    assert result["pass"] is False
    assert result["score_contains_all"]["pass"] is False
    assert result["score_forbidden_absent"]["pass"] is False
    assert result["score_max_chars"]["pass"] is False


def test_structure_scorers_json_sections_and_paths():
    json_output = {"text": '{"a": 1}', "usage": {"input_tokens": 2, "output_tokens": 3}}
    doc_output = {
        "text": "## Summary\nSee src/app.py#L10",
        "usage": {"input_tokens": 2, "output_tokens": 3},
    }

    json_result = codex_scoring.score_json_validity(json_output, require_json=True)
    sections_result = codex_scoring.score_required_sections(
        doc_output, required_sections=["Summary"]
    )
    path_result = codex_scoring.score_file_path_citations(
        doc_output, require_file_paths=True
    )
    token_result = codex_scoring.score_token_usage(doc_output)

    assert json_result["pass"] is True
    assert sections_result["pass"] is True
    assert path_result["pass"] is True
    assert token_result["total_tokens"] == 5


def test_structure_scorers_fail_cases():
    output = {"text": "not json and no sections", "usage": {}}

    assert codex_scoring.score_json_validity(output, require_json=True)["pass"] is False
    assert (
        codex_scoring.score_required_sections(output, required_sections=["Summary"])[
            "pass"
        ]
        is False
    )
    assert (
        codex_scoring.score_file_path_citations(output, require_file_paths=True)["pass"]
        is False
    )


def test_required_sections_match_headings_not_substrings():
    output = {"text": "Summary details without a heading", "usage": {}}

    result = codex_scoring.score_required_sections(
        output, required_sections=["Summary"]
    )

    assert result["pass"] is False


def test_required_sections_accept_headings_with_parenthetical_suffixes():
    output = {"text": "## Summary (Optional)\nDetails here", "usage": {}}

    result = codex_scoring.score_required_sections(
        output, required_sections=["Summary"]
    )

    assert result["pass"] is True


def test_file_path_citations_accept_line_anchors():
    output = {"text": "See src/app.py#L12 for details", "usage": {}}

    result = codex_scoring.score_file_path_citations(output, require_file_paths=True)

    assert result["pass"] is True


def test_score_token_usage_handles_invalid_values():
    output = {"text": "ok", "usage": {"input_tokens": "abc", "output_tokens": None}}
    token_result = codex_scoring.score_token_usage(output)
    assert token_result["input_tokens"] == 0
    assert token_result["output_tokens"] == 0
    assert token_result["total_tokens"] == 0


def test_exact_match_scorer_requires_full_match():
    assert codex_scoring.score_exact_match("ok", exact_match="ok")["pass"] is True
    assert codex_scoring.score_exact_match("ok then", exact_match="ok")["pass"] is False
