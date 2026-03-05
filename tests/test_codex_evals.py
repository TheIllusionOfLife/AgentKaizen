import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import codex_evals


def test_load_cases_jsonl_reads_all_rows(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "prompt": "p1",
                        "must_contain": ["a"],
                        "must_not_contain": [],
                        "max_chars": 10,
                    }
                ),
                json.dumps(
                    {
                        "prompt": "p2",
                        "must_contain": ["b"],
                        "must_not_contain": ["x"],
                        "max_chars": 20,
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    rows = codex_evals.load_cases_jsonl(path)

    assert len(rows) == 2
    assert rows[0]["prompt"] == "p1"


def test_apply_variant_edits_append_prepend_replace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    target.write_text("middle\n", encoding="utf-8")

    variant = {
        "name": "candidate",
        "edits": [
            {"path": "AGENTS.md", "mode": "prepend", "text": "start\n"},
            {"path": "AGENTS.md", "mode": "append", "text": "end\n"},
            {"path": "AGENTS.md", "mode": "replace", "text": "final\n"},
        ],
    }

    codex_evals.apply_variant_edits(workspace, variant)

    assert target.read_text(encoding="utf-8") == "final\n"


def test_apply_variant_edits_rejects_unknown_mode(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("x", encoding="utf-8")

    variant = {
        "name": "bad",
        "edits": [{"path": "AGENTS.md", "mode": "unknown", "text": "x"}],
    }

    try:
        codex_evals.apply_variant_edits(workspace, variant)
    except ValueError as exc:
        assert "Unsupported edit mode" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_scorers():
    assert (
        codex_evals.score_contains_all("hello world", ["hello", "world"])["pass"]
        is True
    )
    assert codex_evals.score_forbidden_absent("hello world", ["bad"])["pass"] is True
    assert codex_evals.score_max_chars("hello", 10)["pass"] is True


def test_normalize_codex_args_includes_skip_git_repo_check():
    assert codex_evals.normalize_codex_args([]) == ["--skip-git-repo-check"]
    assert codex_evals.normalize_codex_args(["--skip-git-repo-check"]) == [
        "--skip-git-repo-check"
    ]


def test_variant_ranking_orders_by_quality_score_desc():
    ranked = codex_evals.rank_variant_results(
        [
            {
                "variant": "baseline",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 0.5}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_json_validity": {"pass": {"true_fraction": 1.0}},
                    "score_required_sections": {"pass": {"true_fraction": 1.0}},
                    "score_file_path_citations": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.0},
                },
            },
            {
                "variant": "candidate",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_json_validity": {"pass": {"true_fraction": 1.0}},
                    "score_required_sections": {"pass": {"true_fraction": 1.0}},
                    "score_file_path_citations": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.0},
                },
            },
        ],
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.2,
        token_regression_threshold=0.2,
    )

    assert ranked[0]["variant"] == "candidate"
    assert ranked[1]["variant"] == "baseline"
    assert ranked[0]["quality_score"] > ranked[1]["quality_score"]


def test_render_ranked_summary_as_list():
    ranked = [
        {
            "variant": "candidate",
            "quality_score": 1.0,
            "summary": {
                "score_contains_all": {"pass": {"true_fraction": 1.0}},
                "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                "score_max_chars": {"pass": {"true_fraction": 1.0}},
                "score_json_validity": {"pass": {"true_fraction": 1.0}},
                "score_required_sections": {"pass": {"true_fraction": 1.0}},
                "score_file_path_citations": {"pass": {"true_fraction": 1.0}},
            },
            "quality_delta_vs_baseline": 0.0,
            "latency_mean": 1.0,
            "token_mean": 100.0,
            "gate_pass": True,
            "gate_reason": "pass",
        }
    ]

    rendered = codex_evals.render_ranked_summary_table(ranked)

    assert "Ranking Summary:" in rendered
    assert "variant: candidate" in rendered
    assert "quality_score: 1.000" in rendered


def test_regression_gate_fails_when_quality_similar_and_latency_worse():
    ranked = codex_evals.rank_variant_results(
        [
            {
                "variant": "baseline",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_json_validity": {"pass": {"true_fraction": 1.0}},
                    "score_required_sections": {"pass": {"true_fraction": 1.0}},
                    "score_file_path_citations": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.0},
                },
            },
            {
                "variant": "candidate",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_json_validity": {"pass": {"true_fraction": 1.0}},
                    "score_required_sections": {"pass": {"true_fraction": 1.0}},
                    "score_file_path_citations": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.5},
                },
            },
        ],
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.2,
        token_regression_threshold=0.2,
    )
    candidate = next(item for item in ranked if item["variant"] == "candidate")
    assert candidate["gate_pass"] is False
    assert "latency_regression" in candidate["gate_reason"]
