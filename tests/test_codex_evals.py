import json
import pathlib
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import agentkaizen.evals as codex_evals

from conftest import set_wandb_target_env


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


def test_load_cases_jsonl_reads_directory_suites(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "core.jsonl").write_text(
        json.dumps({"id": "core-1", "prompt": "p1", "suite": "core"}) + "\n",
        encoding="utf-8",
    )
    (cases_dir / "workflow.jsonl").write_text(
        json.dumps({"id": "workflow-1", "prompt": "p2", "suite": "workflow"}) + "\n",
        encoding="utf-8",
    )

    rows = codex_evals.load_cases_jsonl(cases_dir)

    assert [row["id"] for row in rows] == ["core-1", "workflow-1"]
    assert [row["suite"] for row in rows] == ["core", "workflow"]


def test_load_cases_jsonl_normalizes_optional_builtin_scorer_fields(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "prompt": "p1",
                        "response_schema": {"type": "object", "properties": {}},
                        "must_contain": [],
                        "must_not_contain": [],
                        "max_chars": 10,
                    }
                ),
                json.dumps(
                    {
                        "prompt": "p2",
                        "must_contain": [],
                        "must_not_contain": [],
                        "max_chars": 20,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_evals.load_cases_jsonl(path)

    assert rows[0]["response_schema"] == {"type": "object", "properties": {}}
    assert "response_schema" in rows[1]
    assert rows[1]["response_schema"] is None


def test_load_cases_jsonl_normalizes_optional_min_chars_field(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "prompt": "p1",
                        "min_chars": 20,
                        "must_contain": [],
                        "must_not_contain": [],
                        "max_chars": 40,
                    }
                ),
                json.dumps(
                    {
                        "prompt": "p2",
                        "must_contain": [],
                        "must_not_contain": [],
                        "max_chars": 20,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = codex_evals.load_cases_jsonl(path)

    assert rows[0]["min_chars"] == 20
    assert "min_chars" in rows[1]
    assert rows[1]["min_chars"] is None


def test_builtin_valid_json_case_scorer_uses_builtin_validator():
    scorer = codex_evals.BuiltinValidJSONCaseScorer()

    skipped = scorer.score(output="ok", require_json=True, response_schema=None)
    passed = scorer.score(
        output='{"a":1}',
        require_json=False,
        response_schema={"type": "object", "properties": {}},
    )

    assert skipped["applicable"] is False
    assert passed["pass"] is True
    assert passed["json_valid"] is True


def test_builtin_pydantic_case_scorer_validates_response_schema():
    scorer = codex_evals.BuiltinPydanticCaseScorer()
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }

    passed = scorer.score(output='{"answer":"ok"}', response_schema=schema)
    failed = scorer.score(output='{"count":1}', response_schema=schema)

    assert passed["pass"] is True
    assert failed["pass"] is False


def test_build_eval_scorers_includes_builtin_scorers():
    scorers = codex_evals.build_eval_scorers(
        [
            {
                "prompt": "p1",
                "must_contain": [],
                "must_not_contain": [],
                "max_chars": 10,
                "response_schema": {"type": "object", "properties": {}},
            }
        ]
    )
    names = {scorer.name for scorer in scorers if getattr(scorer, "name", None)}

    assert "builtin_json_validity" in names
    assert "builtin_pydantic" in names


def test_build_eval_scorers_skips_optional_builtin_scorers_without_columns():
    scorers = codex_evals.build_eval_scorers(
        [{"prompt": "p1", "must_contain": [], "must_not_contain": [], "max_chars": 10}]
    )
    names = {scorer.name for scorer in scorers if getattr(scorer, "name", None)}

    assert "score_min_chars" not in names
    assert "builtin_json_validity" not in names
    assert "builtin_pydantic" not in names


def test_build_eval_scorers_includes_min_chars_when_dataset_uses_it():
    scorers = codex_evals.build_eval_scorers(
        [
            {
                "prompt": "p1",
                "must_contain": [],
                "must_not_contain": [],
                "max_chars": 10,
                "min_chars": 3,
            }
        ]
    )
    names = {scorer.name for scorer in scorers if getattr(scorer, "name", None)}

    assert "score_min_chars" in names


def test_load_cases_jsonl_rejects_missing_path(tmp_path):
    missing = tmp_path / "missing.jsonl"

    try:
        codex_evals.load_cases_jsonl(missing)
    except codex_evals.CaseLoadError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("Expected CaseLoadError")


def test_load_cases_jsonl_rejects_empty_directory(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    try:
        codex_evals.load_cases_jsonl(cases_dir)
    except codex_evals.CaseLoadError as exc:
        assert "No JSONL case files" in str(exc)
    else:
        raise AssertionError("Expected CaseLoadError")


def test_load_cases_jsonl_rejects_malformed_json_with_context(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    try:
        codex_evals.load_cases_jsonl(path)
    except codex_evals.CaseLoadError as exc:
        assert "cases.jsonl" in str(exc)
        assert "line 1" in str(exc)
    else:
        raise AssertionError("Expected CaseLoadError")


def test_load_cases_jsonl_rejects_non_object_rows(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('["not", "an", "object"]\n', encoding="utf-8")

    try:
        codex_evals.load_cases_jsonl(path)
    except codex_evals.CaseLoadError as exc:
        assert "cases.jsonl" in str(exc)
        assert "line 1" in str(exc)
        assert "list" in str(exc)
    else:
        raise AssertionError("Expected CaseLoadError")


def test_main_returns_2_when_cases_fail_to_load(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(codex_evals, "ensure_wandb_api_key", lambda: "x")
    set_wandb_target_env(monkeypatch)

    rc = codex_evals.main(["--cases", str(tmp_path / "missing.jsonl")])

    out = capsys.readouterr()
    assert rc == 2
    assert "not found" in out.err


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


def test_apply_variant_edits_rejects_absolute_or_escaping_paths(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("x", encoding="utf-8")

    absolute_variant = {
        "name": "bad-abs",
        "edits": [
            {
                "path": str((workspace / "AGENTS.md").resolve()),
                "mode": "append",
                "text": "x",
            }
        ],
    }
    escaping_variant = {
        "name": "bad-escape",
        "edits": [{"path": "../outside.txt", "mode": "append", "text": "x"}],
    }

    for variant in [absolute_variant, escaping_variant]:
        try:
            codex_evals.apply_variant_edits(workspace, variant)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError")


def test_materialize_external_variant_inputs_copies_external_files(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_file = tmp_path / "skill" / "SKILL.md"
    external_file.parent.mkdir()
    external_file.write_text("original skill\n", encoding="utf-8")

    mapping = codex_evals.materialize_external_variant_inputs(
        workspace,
        {
            "name": "candidate",
            "external_files": [
                {
                    "source": str(external_file),
                    "target": "external_skills/demo/SKILL.md",
                }
            ],
        },
    )

    copied = workspace / "external_skills" / "demo" / "SKILL.md"
    assert copied.read_text(encoding="utf-8") == "original skill\n"
    assert mapping == {str(external_file): Path("external_skills/demo/SKILL.md")}


def test_apply_variant_edits_supports_external_scope_with_materialized_mapping(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_file = tmp_path / "skill" / "SKILL.md"
    external_file.parent.mkdir()
    external_file.write_text("original\n", encoding="utf-8")
    copied = workspace / "external_skills" / "demo" / "SKILL.md"
    copied.parent.mkdir(parents=True)
    copied.write_text("original\n", encoding="utf-8")

    codex_evals.apply_variant_edits(
        workspace,
        {
            "name": "candidate",
            "file_edits": [
                {
                    "source_scope": "external",
                    "path": str(external_file),
                    "mode": "append",
                    "text": "changed\n",
                }
            ],
        },
        external_path_map={str(external_file): Path("external_skills/demo/SKILL.md")},
    )

    assert copied.read_text(encoding="utf-8") == "original\nchanged\n"


def test_resolve_variant_codex_config_prefers_variant_values():
    resolved = codex_evals.resolve_variant_codex_config(
        variant={
            "codex_config": {
                "model": "gpt-5",
                "profile": "safe",
                "codex_args": ["--full-auto"],
            }
        },
        cli_args={
            "model": "o3",
            "profile": "default",
            "sandbox": "workspace-write",
            "codex_args": ["--x"],
        },
    )

    assert resolved["model"] == "gpt-5"
    assert resolved["profile"] == "safe"
    assert resolved["sandbox"] == "workspace-write"
    assert resolved["codex_args"] == ["--full-auto"]


def test_variant_file_edits_rejects_non_list_file_edits():
    try:
        codex_evals._variant_file_edits({"file_edits": "bad"})
    except TypeError as exc:
        assert "file_edits" in str(exc)
    else:
        raise AssertionError("Expected TypeError")


def test_apply_variant_edits_rejects_unknown_source_scope(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("x", encoding="utf-8")

    try:
        codex_evals.apply_variant_edits(
            workspace,
            {
                "name": "bad",
                "file_edits": [
                    {
                        "path": "AGENTS.md",
                        "source_scope": "mystery",
                        "mode": "append",
                        "text": "x",
                    }
                ],
            },
        )
    except ValueError as exc:
        assert "Unsupported source_scope" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_resolve_variant_codex_config_rejects_string_codex_args():
    try:
        codex_evals.resolve_variant_codex_config(
            variant={"name": "bad", "codex_config": {"codex_args": "--full-auto"}},
            cli_args={},
        )
    except ValueError as exc:
        assert "codex_args" in str(exc)
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


def test_regression_gate_does_not_fire_when_quality_not_similar():
    ranked = codex_evals.rank_variant_results(
        [
            {
                "variant": "baseline",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.0},
                },
            },
            {
                "variant": "candidate",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 0.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 0.0}},
                    "score_max_chars": {"pass": {"true_fraction": 0.0}},
                    "score_token_usage": {"total_tokens": {"mean": 300.0}},
                    "model_latency": {"mean": 3.0},
                },
            },
        ],
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.2,
        token_regression_threshold=0.2,
    )
    candidate = next(item for item in ranked if item["variant"] == "candidate")
    assert candidate["gate_pass"] is True


def test_quality_score_uses_baseline_active_checks_only():
    ranked = codex_evals.rank_variant_results(
        [
            {
                "variant": "baseline",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_json_validity": {
                        "pass": {"true_fraction": 0.0},
                        "require_json": {"true_fraction": 0.0},
                    },
                    "score_required_sections": {
                        "pass": {"true_fraction": 0.0},
                        "required_count": {"mean": 0.0},
                    },
                    "score_file_path_citations": {
                        "pass": {"true_fraction": 0.0},
                        "require_file_paths": {"true_fraction": 0.0},
                    },
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
                    "score_json_validity": {
                        "pass": {"true_fraction": 0.0},
                        "require_json": {"true_fraction": 1.0},
                    },
                    "score_required_sections": {
                        "pass": {"true_fraction": 0.0},
                        "required_count": {"mean": 2.0},
                    },
                    "score_file_path_citations": {
                        "pass": {"true_fraction": 0.0},
                        "require_file_paths": {"true_fraction": 1.0},
                    },
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.0},
                },
            },
        ],
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.2,
        token_regression_threshold=0.2,
    )
    candidate = next(item for item in ranked if item["variant"] == "candidate")
    assert candidate["quality_score"] == 1.0


def test_quality_score_includes_exact_match_when_baseline_requires_it():
    ranked = codex_evals.rank_variant_results(
        [
            {
                "variant": "baseline",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_exact_match": {
                        "pass": {"true_fraction": 1.0},
                        "exact_match_required": {"true_fraction": 1.0, "count": 1},
                    },
                },
            },
            {
                "variant": "candidate",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_exact_match": {
                        "pass": {"true_fraction": 0.0},
                        "exact_match_required": {"true_fraction": 1.0, "count": 1},
                    },
                },
            },
        ],
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.2,
        token_regression_threshold=0.2,
    )

    candidate = next(item for item in ranked if item["variant"] == "candidate")
    assert candidate["quality_score"] < 1.0


def test_main_returns_4_when_candidate_fails_gate(monkeypatch):
    monkeypatch.setattr(codex_evals, "ensure_wandb_api_key", lambda: "x")
    set_wandb_target_env(monkeypatch)
    monkeypatch.setattr(codex_evals.weave, "init", lambda _project: None)
    monkeypatch.setattr(
        codex_evals, "load_cases_jsonl", lambda _path: [{"prompt": "p"}]
    )
    monkeypatch.setattr(
        codex_evals,
        "_variants_from_args",
        lambda _paths: [
            {"name": "baseline", "edits": []},
            {"name": "candidate", "edits": []},
        ],
    )
    monkeypatch.setattr(codex_evals, "copy_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        codex_evals, "apply_variant_edits", lambda *_args, **_kwargs: None
    )

    class FakeEvaluation:
        def __init__(self, name, dataset, scorers):
            self.name = name

        def evaluate(self, model):
            if self.name.endswith("baseline"):
                return {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 100.0}},
                    "model_latency": {"mean": 1.0},
                }
            return {
                "score_contains_all": {"pass": {"true_fraction": 1.0}},
                "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                "score_max_chars": {"pass": {"true_fraction": 1.0}},
                "score_token_usage": {"total_tokens": {"mean": 200.0}},
                "model_latency": {"mean": 2.0},
            }

    monkeypatch.setattr(codex_evals.weave, "Evaluation", FakeEvaluation)
    monkeypatch.setattr(codex_evals.asyncio, "run", lambda result: result)

    rc = codex_evals.main(
        [
            "--cases",
            "dummy.jsonl",
            "--variant-file",
            "dummy_variant.json",
        ]
    )
    assert rc == 4


def test_quality_score_uses_applicable_counts_for_mixed_activation():
    summary = {
        "score_contains_all": {"pass": {"true_fraction": 1.0, "count": 10}},
        "score_forbidden_absent": {"pass": {"true_fraction": 1.0, "count": 10}},
        "score_max_chars": {"pass": {"true_fraction": 1.0, "count": 10}},
        "score_json_validity": {
            "pass": {"true_fraction": 0.8, "count": 10},
            "applicable_count": 2,
        },
    }
    quality = codex_evals._quality_score(
        summary,
        [
            "score_contains_all",
            "score_forbidden_absent",
            "score_max_chars",
            "score_json_validity",
        ],
    )
    assert quality == (10 + 10 + 10 + (0.8 * 2)) / (10 + 10 + 10 + 2)


def test_main_missing_wandb_api_key_writes_to_stderr(monkeypatch, capsys):
    monkeypatch.setattr(codex_evals, "ensure_wandb_api_key", lambda: None)
    rc = codex_evals.main([])
    out = capsys.readouterr()
    assert rc == 2
    assert "WANDB_API_KEY" in out.err
    assert out.out == ""


def test_main_succeeds_without_optional_builtin_scorer_columns(
    monkeypatch, capsys, tmp_path
):
    monkeypatch.setattr(codex_evals, "ensure_wandb_api_key", lambda: "x")
    set_wandb_target_env(monkeypatch)
    monkeypatch.setattr(codex_evals.weave, "init", lambda _project: None)

    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "prompt": "Say only: ok",
                "must_contain": ["ok"],
                "must_not_contain": [],
                "exact_match": "ok",
                "max_chars": 40,
                "require_json": False,
                "required_sections": [],
                "require_file_paths": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    variant_path = tmp_path / "variant.json"
    variant_path.write_text(
        json.dumps({"name": "candidate", "edits": []}), encoding="utf-8"
    )

    monkeypatch.setattr(codex_evals, "copy_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        codex_evals, "materialize_external_variant_inputs", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        codex_evals, "apply_variant_edits", lambda *_args, **_kwargs: None
    )

    scorer_names: list[list[str]] = []

    class FakeEvaluation:
        def __init__(self, name, dataset, scorers):
            del name, dataset
            scorer_names.append(
                [scorer.name for scorer in scorers if getattr(scorer, "name", None)]
            )

        def evaluate(self, model):
            del model
            return {
                "score_contains_all": {"pass": {"true_fraction": 1.0}},
                "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                "score_exact_match": {
                    "pass": {"true_fraction": 1.0},
                    "exact_match_required": {"true_fraction": 1.0, "count": 1},
                },
                "score_max_chars": {"pass": {"true_fraction": 1.0}},
                "score_token_usage": {"total_tokens": {"mean": 10.0}},
                "model_latency": {"mean": 1.0},
            }

    monkeypatch.setattr(codex_evals.weave, "Evaluation", FakeEvaluation)
    monkeypatch.setattr(codex_evals.asyncio, "run", lambda result: result)

    rc = codex_evals.main(
        [
            "--cases",
            str(cases_path),
            "--variant-file",
            str(variant_path),
        ]
    )

    out = capsys.readouterr()
    assert rc == 0
    assert scorer_names
    for names in scorer_names:
        assert "builtin_json_validity" not in names
        assert "builtin_pydantic" not in names
    assert "Ranking Summary:" in out.out


def test_codex_variant_model_predict_timeout_raises_runtimeerror(monkeypatch):
    model = codex_evals.CodexVariantModel(workspace="/tmp", timeout_seconds=1)

    def fake_run(*_args, **_kwargs):
        raise codex_evals.subprocess.TimeoutExpired(cmd="codex", timeout=1)

    monkeypatch.setattr(codex_evals.subprocess, "run", fake_run)

    try:
        model.predict("hello")
    except RuntimeError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


def test_regression_gate_handles_zero_baseline_values():
    ranked = codex_evals.rank_variant_results(
        [
            {
                "variant": "baseline",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 0.0}},
                    "model_latency": {"mean": 0.0},
                },
            },
            {
                "variant": "candidate",
                "summary": {
                    "score_contains_all": {"pass": {"true_fraction": 1.0}},
                    "score_forbidden_absent": {"pass": {"true_fraction": 1.0}},
                    "score_max_chars": {"pass": {"true_fraction": 1.0}},
                    "score_token_usage": {"total_tokens": {"mean": 1.0}},
                    "model_latency": {"mean": 1.0},
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
    assert "token_regression" in candidate["gate_reason"]


def test_eval_main_black_box_detects_agents_language_variant(
    monkeypatch, capsys, tmp_path, install_fake_codex
):
    monkeypatch.setattr(codex_evals, "ensure_wandb_api_key", lambda: "x")
    set_wandb_target_env(monkeypatch)
    monkeypatch.setattr(codex_evals.weave, "init", lambda _project: None)
    install_fake_codex()

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.chdir(repo_root)
    (repo_root / "AGENTS.md").write_text(
        "Default repository instructions.\n", encoding="utf-8"
    )
    cases_path = repo_root / "language-steering.jsonl"
    cases_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "jp-summary",
                        "prompt": "Reply in one sentence: what does this repository do?",
                        "must_contain": ["このリポジトリ", "W&B Weave"],
                        "must_not_contain": ["I cannot"],
                        "max_chars": 240,
                        "require_json": False,
                        "required_sections": [],
                        "require_file_paths": False,
                    }
                ),
                json.dumps(
                    {
                        "id": "english-control",
                        "prompt": "Respond in English with one sentence: what does this repository do?",
                        "must_contain": ["This repository", "W&B Weave"],
                        "must_not_contain": [],
                        "max_chars": 240,
                        "require_json": False,
                        "required_sections": [],
                        "require_file_paths": False,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    variant_path = repo_root / "variant.json"
    variant_path.write_text(
        json.dumps(
            {
                "name": "agents-japanese-response",
                "edits": [
                    {
                        "path": "AGENTS.md",
                        "mode": "append",
                        "text": "\nYou must respond in Japanese.\n",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def _fraction(passes: list[bool]) -> dict[str, float]:
        true_count = sum(1 for item in passes if item)
        total = len(passes)
        return {
            "true_fraction": true_count / total if total else 0.0,
            "true_count": float(true_count),
            "false_count": float(total - true_count),
            "count": float(total),
        }

    class FakeEvaluation:
        def __init__(self, name, dataset, scorers):
            del scorers
            self.name = name
            self.dataset = dataset

        async def evaluate(self, model):
            contains_passes: list[bool] = []
            forbidden_passes: list[bool] = []
            max_char_passes: list[bool] = []
            token_totals: list[int] = []
            latencies: list[float] = []

            for case in self.dataset:
                started = perf_counter()
                output = model.predict(case["prompt"])
                latencies.append(perf_counter() - started)
                contains_passes.append(
                    codex_evals.score_contains_all(
                        output["text"], case.get("must_contain", [])
                    )["pass"]
                )
                forbidden_passes.append(
                    codex_evals.score_forbidden_absent(
                        output["text"], case.get("must_not_contain", [])
                    )["pass"]
                )
                max_char_passes.append(
                    codex_evals.score_max_chars(output["text"], case.get("max_chars"))[
                        "pass"
                    ]
                )
                token_totals.append(int(output["usage"].get("total_tokens", 0)))

            return {
                "score_contains_all": {"pass": _fraction(contains_passes)},
                "score_forbidden_absent": {"pass": _fraction(forbidden_passes)},
                "score_max_chars": {"pass": _fraction(max_char_passes)},
                "score_token_usage": {
                    "total_tokens": {
                        "mean": sum(token_totals) / len(token_totals),
                    }
                },
                "model_latency": {"mean": sum(latencies) / len(latencies)},
            }

    monkeypatch.setattr(codex_evals.weave, "Evaluation", FakeEvaluation)

    rc = codex_evals.main(
        [
            "--cases",
            str(cases_path),
            "--variant-file",
            str(variant_path),
        ]
    )

    out = capsys.readouterr()
    assert rc == 0
    assert '"variant": "baseline"' in out.out
    assert '"variant": "agents-japanese-response"' in out.out
    assert "1. variant: agents-japanese-response" in out.out
    assert "2. variant: baseline" in out.out
