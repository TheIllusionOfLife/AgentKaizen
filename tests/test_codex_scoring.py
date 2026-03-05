import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_scoring


def test_evaluate_output_pass_case():
    result = codex_scoring.evaluate_output(
        output="hello world",
        must_contain=["hello"],
        must_not_contain=["forbidden"],
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
        max_chars=3,
    )

    assert result["pass"] is False
    assert result["score_contains_all"]["pass"] is False
    assert result["score_forbidden_absent"]["pass"] is False
    assert result["score_max_chars"]["pass"] is False
