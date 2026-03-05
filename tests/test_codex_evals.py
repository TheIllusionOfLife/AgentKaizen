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
