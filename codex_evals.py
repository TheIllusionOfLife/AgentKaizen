from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import weave

from codex_scoring import score_contains_all, score_forbidden_absent, score_max_chars
from codex_weave import (
    DEFAULT_ENTITY,
    DEFAULT_PROJECT,
    ensure_wandb_api_key,
    parse_codex_jsonl,
)


def load_cases_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def load_variant_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_variant_edits(workspace: Path, variant: dict[str, Any]) -> None:
    edits = variant.get("edits", [])
    for edit in edits:
        rel_path = edit["path"]
        mode = edit["mode"]
        text = edit["text"]
        target = workspace / rel_path

        if not target.exists():
            raise FileNotFoundError(f"Variant edit target not found: {rel_path}")

        original = target.read_text(encoding="utf-8")
        if mode == "append":
            updated = original + text
        elif mode == "prepend":
            updated = text + original
        elif mode == "replace":
            updated = text
        else:
            raise ValueError(f"Unsupported edit mode: {mode}")

        target.write_text(updated, encoding="utf-8")


def copy_workspace(src_root: Path, dst_root: Path) -> None:
    shutil.copytree(
        src_root,
        dst_root,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            "*.pyc",
            "*.pyo",
        ),
    )


contains_all_scorer = weave.op()(score_contains_all)
forbidden_absent_scorer = weave.op()(score_forbidden_absent)
max_chars_scorer = weave.op()(score_max_chars)


def normalize_codex_args(codex_args: list[str]) -> list[str]:
    if "--skip-git-repo-check" in codex_args:
        return codex_args
    return [*codex_args, "--skip-git-repo-check"]


class CodexVariantModel(weave.Model):
    workspace: str
    codex_model: str | None = None
    sandbox: str | None = None
    profile: str | None = None
    codex_args: list[str] = []

    @weave.op()
    def predict(self, prompt: str) -> str:
        command = ["codex", "exec", "-C", self.workspace, "--json"]
        if self.codex_model:
            command.extend(["--model", self.codex_model])
        if self.sandbox:
            command.extend(["--sandbox", self.sandbox])
        if self.profile:
            command.extend(["--profile", self.profile])
        command.extend(normalize_codex_args(self.codex_args))
        command.append(prompt)

        proc = subprocess.run(command, capture_output=True, text=True)
        parsed = parse_codex_jsonl(proc.stdout.splitlines())
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exec failed (exit={proc.returncode}): {proc.stderr.strip()}"
            )
        return parsed.final_message


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Weave Evals for Codex using document variants"
    )
    parser.add_argument(
        "--cases",
        default="evals/cases.jsonl",
        help="Path to JSONL evaluation cases",
    )
    parser.add_argument(
        "--variant-file",
        action="append",
        default=[],
        help="Path to variant JSON (repeatable)",
    )
    parser.add_argument("--entity", default=DEFAULT_ENTITY, help="W&B entity/team")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="W&B project")
    parser.add_argument("--model", help="Codex model")
    parser.add_argument("--sandbox", help="Codex sandbox mode")
    parser.add_argument("--profile", help="Codex profile")
    parser.add_argument(
        "--codex-arg",
        action="append",
        default=[],
        help="Extra argument forwarded to codex exec (repeatable)",
    )
    return parser


def _variants_from_args(variant_files: list[str]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = [{"name": "baseline", "edits": []}]
    for variant_path in variant_files:
        variant = load_variant_file(Path(variant_path))
        if "name" not in variant:
            raise ValueError(f"Variant file missing 'name': {variant_path}")
        variants.append(variant)
    return variants


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not ensure_wandb_api_key():
        print("WANDB_API_KEY is required to run evals.")
        return 2

    project_path = f"{args.entity}/{args.project}"
    weave.init(project_path)

    repo_root = Path.cwd()
    cases = load_cases_jsonl(Path(args.cases))
    variants = _variants_from_args(args.variant_file)

    for variant in variants:
        with tempfile.TemporaryDirectory(prefix="codex-eval-") as td:
            temp_workspace = Path(td) / "workspace"
            copy_workspace(repo_root, temp_workspace)
            apply_variant_edits(temp_workspace, variant)

            model = CodexVariantModel(
                workspace=str(temp_workspace),
                codex_model=args.model,
                sandbox=args.sandbox,
                profile=args.profile,
                codex_args=args.codex_arg,
            )
            evaluation = weave.Evaluation(
                name=f"codex-doc-impact-{variant['name']}",
                dataset=cases,
                scorers=[
                    contains_all_scorer,
                    forbidden_absent_scorer,
                    max_chars_scorer,
                ],
            )
            result = asyncio.run(evaluation.evaluate(model))
            print(
                json.dumps(
                    {"variant": variant["name"], "summary": result}, ensure_ascii=True
                )
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
