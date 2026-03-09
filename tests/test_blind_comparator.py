"""Tests for Feature 3: Blind A/B Comparator with Diagnostic Reasoning."""

import json
import pathlib
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


# --- ComparatorResult and ComparatorScorer ---


def test_comparator_result_dataclass():
    """ComparatorResult construction."""
    from agentkaizen._comparator import ComparatorResult

    result = ComparatorResult(
        winner="A",
        rubric_scores={
            "instruction_adherence": {"A": 4, "B": 2},
            "completeness": {"A": 5, "B": 3},
        },
        reasoning="A followed instructions more closely",
        winner_strengths=["Clear structure", "Followed rules"],
        loser_weaknesses=["Missed key instruction", "Verbose"],
    )
    assert result.winner == "A"
    assert result.rubric_scores["instruction_adherence"]["A"] == 4


def test_comparator_shuffles_outputs():
    """Assert random shuffling occurs — verify via mock random."""
    from agentkaizen._comparator import ComparatorScorer

    scorer = ComparatorScorer(rubric="test rubric")

    # Mock the runner
    mock_runner = MagicMock()
    mock_result = MagicMock()
    mock_result.final_message = json.dumps(
        {
            "winner": "A",
            "rubric_scores": {
                "instruction_adherence": {"A": 4, "B": 3},
            },
            "reasoning": "A is better",
            "winner_strengths": ["Good"],
            "loser_weaknesses": ["Bad"],
        }
    )
    mock_runner.run.return_value = mock_result

    with (
        patch("agentkaizen._comparator.get_runner", return_value=mock_runner),
        patch("agentkaizen._comparator.random.random", return_value=0.3),
    ):
        # random() < 0.5 → swap
        scorer.compare("output_a", "output_b", "test prompt")
        # When swapped: A→B, B→A. Winner "A" in response maps to original "B"
        call_args = mock_runner.run.call_args[0][0]
        # Verify the prompt was built (contains response tags)
        assert "<response_a>" in call_args or "response_a" in call_args.lower()


def test_comparator_deshuffle():
    """Winner correctly attributed after de-shuffle."""
    from agentkaizen._comparator import ComparatorScorer

    scorer = ComparatorScorer(rubric="test rubric")

    mock_runner = MagicMock()
    mock_result = MagicMock()
    mock_result.final_message = json.dumps(
        {
            "winner": "A",
            "rubric_scores": {
                "instruction_adherence": {"A": 4, "B": 3},
            },
            "reasoning": "A is better",
            "winner_strengths": ["Good"],
            "loser_weaknesses": ["Bad"],
        }
    )
    mock_runner.run.return_value = mock_result

    # No swap (random >= 0.5)
    with (
        patch("agentkaizen._comparator.get_runner", return_value=mock_runner),
        patch("agentkaizen._comparator.random.random", return_value=0.7),
    ):
        result = scorer.compare("output_a", "output_b", "test prompt")
        assert result.winner == "A"  # No swap, so A stays A

    # With swap (random < 0.5)
    with (
        patch("agentkaizen._comparator.get_runner", return_value=mock_runner),
        patch("agentkaizen._comparator.random.random", return_value=0.3),
    ):
        result = scorer.compare("output_a", "output_b", "test prompt")
        assert result.winner == "B"  # Swapped: response's "A" maps to original "B"


def test_comparator_parse_json():
    """Valid and malformed JSON handling."""
    from agentkaizen._comparator import ComparatorScorer

    scorer = ComparatorScorer(rubric="test")

    # Valid JSON
    mock_runner = MagicMock()
    mock_result = MagicMock()
    mock_result.final_message = json.dumps(
        {
            "winner": "B",
            "rubric_scores": {"completeness": {"A": 2, "B": 5}},
            "reasoning": "B is more complete",
            "winner_strengths": ["Thorough"],
            "loser_weaknesses": ["Incomplete"],
        }
    )
    mock_runner.run.return_value = mock_result

    with (
        patch("agentkaizen._comparator.get_runner", return_value=mock_runner),
        patch("agentkaizen._comparator.random.random", return_value=0.7),
    ):
        result = scorer.compare("a", "b", "prompt")
        assert result.winner == "B"

    # Malformed JSON → tie fallback
    mock_result.final_message = "this is not json"
    with (
        patch("agentkaizen._comparator.get_runner", return_value=mock_runner),
        patch("agentkaizen._comparator.random.random", return_value=0.7),
    ):
        result = scorer.compare("a", "b", "prompt")
        assert result.winner == "tie"
        assert (
            "error" in result.reasoning.lower() or "failed" in result.reasoning.lower()
        )


def test_comparator_tie():
    """Comparator returns tie result."""
    from agentkaizen._comparator import ComparatorScorer

    scorer = ComparatorScorer(rubric="test")

    mock_runner = MagicMock()
    mock_result = MagicMock()
    mock_result.final_message = json.dumps(
        {
            "winner": "tie",
            "rubric_scores": {},
            "reasoning": "Both are equivalent",
            "winner_strengths": [],
            "loser_weaknesses": [],
        }
    )
    mock_runner.run.return_value = mock_result

    with (
        patch("agentkaizen._comparator.get_runner", return_value=mock_runner),
        patch("agentkaizen._comparator.random.random", return_value=0.7),
    ):
        result = scorer.compare("a", "b", "prompt")
        assert result.winner == "tie"


# --- pairwise integration ---


def test_pairwise_integration():
    """Mock comparator, verify integration with ranking."""
    from agentkaizen._comparator import ComparatorResult, ComparatorScorer
    from agentkaizen.evals import run_pairwise_comparison

    mock_comparator = MagicMock(spec=ComparatorScorer)
    mock_comparator.compare.return_value = ComparatorResult(
        winner="B",
        rubric_scores={"instruction_adherence": {"A": 3, "B": 5}},
        reasoning="B is better",
        winner_strengths=["Better"],
        loser_weaknesses=["Worse"],
    )

    baseline_results = [
        {"idx": 0, "output": "baseline output", "prompt": "test prompt"}
    ]
    variant_results = [{"idx": 0, "output": "variant output", "prompt": "test prompt"}]
    cases = [{"prompt": "test prompt"}]

    comparison = run_pairwise_comparison(
        baseline_results, variant_results, cases, mock_comparator
    )

    assert len(comparison) == 1
    assert comparison[0]["winner"] in ("baseline", "candidate", "tie")
    mock_comparator.compare.assert_called_once()


# --- CLI flag wiring ---


def test_compare_flag_activates_comparator():
    """CLI flag --compare is registered in arg parser."""
    from agentkaizen.evals import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["--compare"])
    assert args.compare is True


def test_compare_flag_default_false():
    """--compare defaults to False."""
    from agentkaizen.evals import _build_parser

    parser = _build_parser()
    args = parser.parse_args([])
    assert args.compare is False


# --- gate_pass unaffected ---


def test_compare_does_not_affect_gate():
    """Verify gate_pass unchanged by comparator results."""
    from agentkaizen.evals import rank_variant_results

    results = [
        {
            "variant": "baseline",
            "summary": {
                "score_contains_all": {
                    "pass": {
                        "true_fraction": 1.0,
                        "count": 5,
                        "true_count": 5,
                        "false_count": 0,
                    }
                },
                "score_forbidden_absent": {
                    "pass": {
                        "true_fraction": 1.0,
                        "count": 5,
                        "true_count": 5,
                        "false_count": 0,
                    }
                },
                "score_max_chars": {
                    "pass": {
                        "true_fraction": 1.0,
                        "count": 5,
                        "true_count": 5,
                        "false_count": 0,
                    }
                },
            },
        },
        {
            "variant": "candidate",
            "summary": {
                "score_contains_all": {
                    "pass": {
                        "true_fraction": 1.0,
                        "count": 5,
                        "true_count": 5,
                        "false_count": 0,
                    }
                },
                "score_forbidden_absent": {
                    "pass": {
                        "true_fraction": 1.0,
                        "count": 5,
                        "true_count": 5,
                        "false_count": 0,
                    }
                },
                "score_max_chars": {
                    "pass": {
                        "true_fraction": 1.0,
                        "count": 5,
                        "true_count": 5,
                        "false_count": 0,
                    }
                },
            },
            # Simulated comparator metadata — should NOT affect gate
            "comparator_wins": 0,
            "comparator_reasoning_summary": "Baseline was better",
        },
    ]

    ranked = rank_variant_results(
        results,
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.20,
        token_regression_threshold=0.20,
    )

    candidate = next(r for r in ranked if r["variant"] == "candidate")
    # gate_pass should still be True — comparator info is report-only
    assert candidate["gate_pass"] is True
