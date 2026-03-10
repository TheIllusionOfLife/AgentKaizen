"""Tests for render_eval_interpretation — human-readable analysis with next actions."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def _make_summary(
    contains_frac=1.0,
    contains_stddev=0.0,
    n_runs=None,
    min_chars_frac=1.0,
):
    """Build a minimal summary dict for testing."""
    pass_block = {
        "true_fraction": contains_frac,
        "stddev": contains_stddev,
        "count": 10,
        "true_count": int(contains_frac * 10),
        "false_count": 10 - int(contains_frac * 10),
    }
    if n_runs is not None:
        pass_block["n_runs"] = n_runs
    return {
        "score_contains_all": {"pass": pass_block},
        "score_forbidden_absent": {
            "pass": {"true_fraction": 1.0, "stddev": 0.0, "count": 10}
        },
        "score_min_chars": {
            "pass": {
                "true_fraction": min_chars_frac,
                "stddev": 0.0,
                "count": 10,
            }
        },
    }


def _make_ranked(variant_items):
    """Build ranked list from (name, delta, gate_pass, gate_reason, summary) tuples."""
    ranked = []
    baseline_score = 0.857
    for name, delta, gate_pass, gate_reason, summary in variant_items:
        quality_score = baseline_score + delta if name != "baseline" else baseline_score
        # Extract n_runs from summary pass stats — mirrors rank_variant_results_aggregated
        n_runs = None
        for key in ("score_contains_all", "score_forbidden_absent", "score_min_chars"):
            ps = summary.get(key, {}).get("pass", {})
            if "n_runs" in ps:
                n_runs = ps["n_runs"]
                break
        item: dict = {
            "variant": name,
            "quality_score": quality_score,
            "quality_delta_vs_baseline": delta,
            "gate_pass": gate_pass,
            "gate_reason": gate_reason,
            "latency_mean": None,
            "token_mean": None,
            "summary": summary,
        }
        if n_runs is not None:
            item["n_runs"] = n_runs
        ranked.append(item)
    return ranked


# --- no improvement ---


def test_interpretation_no_change():
    """Delta = 0.0 produces 'no measurable improvement' message."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", _make_summary()),
            ("my-variant", 0.0, True, "pass", _make_summary()),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "no measurable improvement" in out.lower()
    assert "my-variant" in out


def test_interpretation_no_change_suggests_steering_surface():
    """No-change result suggests checking the steering surface."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", _make_summary()),
            ("readme-edit", 0.0, True, "pass", _make_summary()),
        ]
    )
    out = render_eval_interpretation(ranked)
    # Should suggest inspecting outputs or checking the right surface
    assert "--show-outputs" in out or "steering surface" in out.lower()


# --- clear winner ---


def test_interpretation_clear_winner():
    """Positive delta + gate_pass → promote recommendation."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked(
        [
            ("candidate", 0.05, True, "pass", _make_summary()),
            ("baseline", 0.0, True, "baseline", _make_summary()),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "promot" in out.lower()
    assert "candidate" in out


# --- quality improved but gated out ---


def test_interpretation_quality_improved_gate_fail():
    """Positive delta but gate_pass=False → quality gain with efficiency cost."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked(
        [
            ("candidate", 0.05, False, "latency_regression", _make_summary()),
            ("baseline", 0.0, True, "baseline", _make_summary()),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "latency" in out.lower() or "regression" in out.lower()
    assert "quality" in out.lower()


# --- regression ---


def test_interpretation_quality_regression():
    """Negative delta produces warning to discard."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", _make_summary()),
            ("bad-variant", -0.05, False, "quality_regression", _make_summary()),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "regress" in out.lower() or "worse" in out.lower()
    assert "bad-variant" in out


# --- persistent failing scorer ---


def test_interpretation_flags_failing_contains():
    """contains_pass < threshold → flags specific scorer and suggests --show-outputs."""
    from agentkaizen.evals import render_eval_interpretation

    summary = _make_summary(contains_frac=0.5)
    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", summary),
            ("variant", 0.0, True, "pass", summary),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "contains" in out.lower() or "required content" in out.lower()
    assert "--show-outputs" in out


def test_interpretation_flags_zero_min_chars():
    """min_chars_pass = 0.0 → flags responses too short."""
    from agentkaizen.evals import render_eval_interpretation

    summary = _make_summary(min_chars_frac=0.0)
    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", summary),
            ("variant", 0.0, True, "pass", summary),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert (
        "short" in out.lower() or "min_chars" in out.lower() or "length" in out.lower()
    )


# --- variance analysis (multi-run) ---


def test_interpretation_zero_variance_deterministic():
    """stddev=0.0 on failing scorer → 'systematic, not noise'."""
    from agentkaizen.evals import render_eval_interpretation

    summary = _make_summary(contains_frac=0.5, contains_stddev=0.0, n_runs=3)
    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", summary),
            ("variant", 0.0, True, "pass", summary),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "systematic" in out.lower() or "deterministic" in out.lower()


def test_interpretation_high_variance():
    """stddev > 0.1 → suggests running more iterations."""
    from agentkaizen.evals import render_eval_interpretation

    summary = _make_summary(contains_frac=0.7, contains_stddev=0.15, n_runs=3)
    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", summary),
            ("variant", 0.0, True, "pass", summary),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "variance" in out.lower() or "runs" in out.lower()


# --- structure ---


def test_interpretation_has_sections():
    """Output has Interpretation and Next Actions sections."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked(
        [
            ("baseline", 0.0, True, "baseline", _make_summary()),
            ("variant", 0.0, True, "pass", _make_summary()),
        ]
    )
    out = render_eval_interpretation(ranked)
    assert "Interpretation" in out
    assert "Next Action" in out


def test_interpretation_baseline_only():
    """No non-baseline variants → graceful empty output."""
    from agentkaizen.evals import render_eval_interpretation

    ranked = _make_ranked([("baseline", 0.0, True, "baseline", _make_summary())])
    out = render_eval_interpretation(ranked)
    assert isinstance(out, str)
    # Should not crash; may be empty or minimal
