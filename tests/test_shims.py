"""Smoke tests: verify root shim modules re-export expected names."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def test_codex_weave_exports():
    from codex_weave import (
        main,
        resolve_weave_project,
        parse_codex_jsonl,
        build_codex_command,
    )

    assert callable(main)
    assert callable(resolve_weave_project)
    assert callable(parse_codex_jsonl)
    assert callable(build_codex_command)


def test_codex_evals_exports():
    from codex_evals import main

    assert callable(main)


def test_codex_casegen_exports():
    from codex_casegen import main

    assert callable(main)


def test_codex_interactive_sync_exports():
    from codex_interactive_sync import main

    assert callable(main)


def test_codex_interactive_scoring_exports():
    from codex_interactive_scoring import main

    assert callable(main)


def test_codex_scoring_exports():
    from codex_scoring import evaluate_output, score_contains_all

    assert callable(evaluate_output)
    assert callable(score_contains_all)
