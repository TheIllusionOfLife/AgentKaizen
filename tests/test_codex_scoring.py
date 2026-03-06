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


def test_min_chars_scorer_enforces_minimum_output_length():
    passed = codex_scoring.score_min_chars("hello world", min_chars=5)
    failed = codex_scoring.score_min_chars("hey", min_chars=5)

    assert passed["pass"] is True
    assert failed["pass"] is False
    assert failed["min_chars"] == 5


def test_required_content_groups_requires_one_match_per_group():
    output = "Uses W&B Weave and uv for workflows."

    passed = codex_scoring.score_required_content_groups(
        output,
        required_content_groups=[["W&B", "Weights & Biases"], ["uv", "pip"]],
    )
    failed = codex_scoring.score_required_content_groups(
        output,
        required_content_groups=[["W&B", "Weights & Biases"], ["pytest", "unittest"]],
    )

    assert passed["pass"] is True
    assert failed["pass"] is False
    assert failed["missing_group_count"] == 1


def test_file_path_citations_can_require_multiple_paths():
    output = {"text": "See src/app.py#L12 and tests/test_app.py#L8", "usage": {}}

    passed = codex_scoring.score_file_path_citations(
        output, require_file_paths=True, min_file_paths=2
    )
    failed = codex_scoring.score_file_path_citations(
        output, require_file_paths=True, min_file_paths=3
    )

    assert passed["pass"] is True
    assert failed["pass"] is False
    assert failed["path_count"] == 2


def test_file_path_citations_accept_root_level_filenames():
    output = {"text": "See README.md and pyproject.toml for details", "usage": {}}

    result = codex_scoring.score_file_path_citations(
        output, require_file_paths=True, min_file_paths=2
    )

    assert result["pass"] is True
    assert result["path_count"] == 2


def test_evaluate_output_includes_new_local_scorers():
    result = codex_scoring.evaluate_output(
        output="Uses W&B Weave in docs. See src/app.py#L10",
        must_contain=["W&B"],
        min_chars=10,
        required_content_groups=[["W&B", "Weights & Biases"], ["docs", "README"]],
        require_file_paths=True,
        min_file_paths=1,
    )

    assert result["pass"] is True
    assert result["score_min_chars"]["pass"] is True
    assert result["score_required_content_groups"]["pass"] is True
    assert result["score_file_path_citations"]["pass"] is True
