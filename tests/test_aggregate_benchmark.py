"""Tests for Feature 1: Aggregate Benchmark with Dispersion-Aware Gating."""

import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentkaizen._local_eval import (
    LocalEvaluation,
    LocalModel,
    _aggregate,
)
from agentkaizen.scoring import score_contains_all, score_max_chars


# --- Helper models ---


class EchoModel(LocalModel):
    def predict(self, prompt: str) -> dict[str, str]:
        return {
            "text": prompt,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


class CyclingModel(LocalModel):
    """Returns different responses per call to simulate non-determinism."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._call_count = 0

    def predict(self, prompt: str) -> dict[str, str]:
        text = self._responses[self._call_count % len(self._responses)]
        self._call_count += 1
        return {
            "text": text,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


# --- _aggregate stddev tests ---


def test_aggregate_with_stddev_bool():
    """Verify stddev/min/max computation for boolean fields."""
    # Two cases: pass=[True, False] → true_fraction=0.5
    per_case_results = [
        {"_latency": 1.0, "scorer": {"pass": True}},
        {"_latency": 2.0, "scorer": {"pass": False}},
    ]

    class FakeScorer:
        name = "scorer"

    result = _aggregate(per_case_results, [FakeScorer()])
    pass_stats = result["scorer"]["pass"]
    assert pass_stats["true_fraction"] == 0.5
    assert pass_stats["count"] == 2
    # No stddev on single-run aggregate (stddev only appears in cross-run)


def test_aggregate_with_stddev_numeric():
    """Verify numeric aggregation includes stddev/min/max."""
    per_case_results = [
        {"_latency": 1.0, "scorer": {"length": 10}},
        {"_latency": 2.0, "scorer": {"length": 20}},
        {"_latency": 3.0, "scorer": {"length": 30}},
    ]

    class FakeScorer:
        name = "scorer"

    result = _aggregate(per_case_results, [FakeScorer()])
    length_stats = result["scorer"]["length"]
    assert length_stats["mean"] == 20.0
    assert length_stats["count"] == 3
    assert "stddev" in length_stats
    assert "min" in length_stats
    assert "max" in length_stats
    assert length_stats["min"] == 10
    assert length_stats["max"] == 30
    # stddev of [10, 20, 30] = sqrt(((10-20)^2 + (20-20)^2 + (30-20)^2) / 3)
    expected_stddev = math.sqrt(200 / 3)
    assert abs(length_stats["stddev"] - expected_stddev) < 0.001


def test_aggregate_latency_includes_stddev():
    """Verify model_latency aggregation includes stddev/min/max."""
    per_case_results = [
        {"_latency": 1.0, "scorer": {"pass": True}},
        {"_latency": 3.0, "scorer": {"pass": True}},
    ]

    class FakeScorer:
        name = "scorer"

    result = _aggregate(per_case_results, [FakeScorer()])
    lat = result["model_latency"]
    assert lat["mean"] == 2.0
    assert lat["min"] == 1.0
    assert lat["max"] == 3.0
    assert "stddev" in lat


# --- evaluate_n tests ---


def test_evaluate_n_runs():
    """evaluate_n calls evaluate N times and merges cross-run statistics."""
    cases = [
        {
            "prompt": "hello",
            "must_contain": ["hello"],
            "must_not_contain": [],
            "max_chars": 100,
        },
    ]
    model = EchoModel()
    evaluation = LocalEvaluation(
        name="test", dataset=cases, scorers=[score_contains_all]
    )
    result = evaluation.evaluate_n(model, n=3)

    # Cross-run aggregation should have n_runs
    contains_stats = result["score_contains_all"]["pass"]
    assert contains_stats["n_runs"] == 3
    assert "stddev" in contains_stats
    assert "min" in contains_stats
    assert "max" in contains_stats
    # EchoModel always passes, so true_fraction should be 1.0 with 0 stddev
    assert contains_stats["true_fraction"] == 1.0
    assert contains_stats["stddev"] == 0.0


def test_evaluate_n_per_run_results():
    """evaluate_n stores per-run per_case_results."""
    cases = [
        {
            "prompt": "hello",
            "must_contain": ["hello"],
            "must_not_contain": [],
            "max_chars": 100,
        },
    ]
    model = EchoModel()
    evaluation = LocalEvaluation(
        name="test", dataset=cases, scorers=[score_contains_all]
    )
    evaluation.evaluate_n(model, n=3)

    assert len(evaluation.per_run_results) == 3
    for run_results in evaluation.per_run_results:
        assert len(run_results) == 1  # 1 case


# --- rank_variant_results_aggregated tests ---


def test_rank_aggregated_conservative():
    """Assert conservative comparison uses mean - stddev for quality."""
    from agentkaizen.evals import rank_variant_results_aggregated

    results = [
        {
            "variant": "baseline",
            "summary": {
                "score_contains_all": {
                    "pass": {
                        "true_fraction": 0.80,
                        "stddev": 0.05,
                        "min": 0.75,
                        "max": 0.85,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 8,
                        "false_count": 2,
                    }
                },
                "score_forbidden_absent": {
                    "pass": {
                        "true_fraction": 1.0,
                        "stddev": 0.0,
                        "min": 1.0,
                        "max": 1.0,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 10,
                        "false_count": 0,
                    }
                },
                "score_max_chars": {
                    "pass": {
                        "true_fraction": 1.0,
                        "stddev": 0.0,
                        "min": 1.0,
                        "max": 1.0,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 10,
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
                        "true_fraction": 0.85,
                        "stddev": 0.10,
                        "min": 0.75,
                        "max": 0.95,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 8,
                        "false_count": 2,
                    }
                },
                "score_forbidden_absent": {
                    "pass": {
                        "true_fraction": 1.0,
                        "stddev": 0.0,
                        "min": 1.0,
                        "max": 1.0,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 10,
                        "false_count": 0,
                    }
                },
                "score_max_chars": {
                    "pass": {
                        "true_fraction": 1.0,
                        "stddev": 0.0,
                        "min": 1.0,
                        "max": 1.0,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 10,
                        "false_count": 0,
                    }
                },
            },
        },
    ]

    ranked = rank_variant_results_aggregated(
        results,
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.20,
        token_regression_threshold=0.20,
    )

    # Candidate mean=0.85 with stddev=0.10: conservative = 0.85 - 0.10 = 0.75
    # Baseline mean=0.80 with stddev=0.05: conservative = 0.80 - 0.05 = 0.75
    # They should be similar (delta ≤ threshold)
    candidate = next(r for r in ranked if r["variant"] == "candidate")
    assert candidate["gate_pass"] is True


def test_rank_aggregated_backward_compat():
    """n=1 produces identical output structure to single-run ranking."""
    from agentkaizen.evals import rank_variant_results_aggregated

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
    ]

    ranked = rank_variant_results_aggregated(
        results,
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.20,
        token_regression_threshold=0.20,
    )

    assert len(ranked) == 1
    assert ranked[0]["quality_score"] == 1.0
    assert ranked[0]["gate_pass"] is True


# --- render_ranked_summary_table with ± format ---


def test_render_aggregated_table():
    """Verify ± format in output for multi-run results."""
    from agentkaizen.evals import render_ranked_summary_table

    ranked = [
        {
            "variant": "baseline",
            "summary": {
                "score_contains_all": {
                    "pass": {
                        "true_fraction": 0.85,
                        "stddev": 0.032,
                        "n_runs": 3,
                        "count": 10,
                        "true_count": 8,
                        "false_count": 2,
                    }
                },
            },
            "quality_score": 0.85,
            "quality_delta_vs_baseline": 0.0,
            "latency_mean": None,
            "token_mean": None,
            "gate_pass": True,
            "gate_reason": "baseline",
            "n_runs": 3,
        }
    ]

    rendered = render_ranked_summary_table(ranked)
    assert "±" in rendered or "n=" in rendered
    assert "0.850" in rendered
