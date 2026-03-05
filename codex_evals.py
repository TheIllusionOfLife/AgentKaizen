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

from codex_scoring import (
    score_contains_all,
    score_file_path_citations,
    score_forbidden_absent,
    score_json_validity,
    score_max_chars,
    score_required_sections,
    score_token_usage,
)
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
    workspace_resolved = workspace.resolve()
    for edit in edits:
        rel_path = Path(edit["path"])
        mode = edit["mode"]
        text = edit["text"]
        if rel_path.is_absolute():
            raise ValueError(f"Variant edit path must be relative: {rel_path}")
        target = (workspace_resolved / rel_path).resolve()
        if not target.is_relative_to(workspace_resolved):
            raise ValueError(f"Variant edit path escapes workspace: {rel_path}")

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
json_validity_scorer = weave.op()(score_json_validity)
required_sections_scorer = weave.op()(score_required_sections)
file_path_citations_scorer = weave.op()(score_file_path_citations)
token_usage_scorer = weave.op()(score_token_usage)


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
    timeout_seconds: int = 300

    @weave.op()
    def predict(self, prompt: str) -> dict[str, Any]:
        command = ["codex", "exec", "-C", self.workspace, "--json"]
        if self.codex_model:
            command.extend(["--model", self.codex_model])
        if self.sandbox:
            command.extend(["--sandbox", self.sandbox])
        if self.profile:
            command.extend(["--profile", self.profile])
        command.extend(normalize_codex_args(self.codex_args))
        command.append(prompt)

        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"codex exec timed out after {self.timeout_seconds} seconds"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exec failed (exit={proc.returncode}): {proc.stderr.strip()}"
            )
        parsed = parse_codex_jsonl(proc.stdout.splitlines())
        return {"text": parsed.final_message, "usage": parsed.usage}


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
    parser.add_argument(
        "--quality-similar-threshold",
        type=float,
        default=0.02,
        help="Quality delta at or below this is considered similar",
    )
    parser.add_argument(
        "--latency-regression-threshold",
        type=float,
        default=0.20,
        help="Fail when candidate latency exceeds baseline by this fraction",
    )
    parser.add_argument(
        "--token-regression-threshold",
        type=float,
        default=0.20,
        help="Fail when candidate token usage exceeds baseline by this fraction",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Timeout for each codex exec call in seconds",
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


def _extract_true_fraction(summary: dict[str, Any], scorer_key: str) -> float:
    return float(summary.get(scorer_key, {}).get("pass", {}).get("true_fraction", 0.0))


def _extract_mean(
    summary: dict[str, Any], scorer_key: str, field: str | None = None
) -> float | None:
    scorer_summary = summary.get(scorer_key, {})
    if not isinstance(scorer_summary, dict):
        return None
    if field is None:
        value = scorer_summary.get("mean")
    else:
        field_summary = scorer_summary.get(field, {})
        if not isinstance(field_summary, dict):
            return None
        value = field_summary.get("mean")
    if value is None:
        return None
    return float(value)


def _quality_score(summary: dict[str, Any], quality_keys: list[str]) -> float:
    values = [_extract_true_fraction(summary, key) for key in quality_keys]
    return sum(values) / len(values)


def _active_quality_keys(summary: dict[str, Any]) -> list[str]:
    keys = ["score_contains_all", "score_forbidden_absent", "score_max_chars"]

    json_required_fraction = float(
        summary.get("score_json_validity", {})
        .get("require_json", {})
        .get("true_fraction", 0.0)
        or 0.0
    )
    if json_required_fraction > 0.0:
        keys.append("score_json_validity")

    required_sections_mean = float(
        summary.get("score_required_sections", {})
        .get("required_count", {})
        .get("mean", 0.0)
        or 0.0
    )
    if required_sections_mean > 0.0:
        keys.append("score_required_sections")

    require_paths_fraction = float(
        summary.get("score_file_path_citations", {})
        .get("require_file_paths", {})
        .get("true_fraction", 0.0)
        or 0.0
    )
    if require_paths_fraction > 0.0:
        keys.append("score_file_path_citations")

    return keys


def rank_variant_results(
    results: list[dict[str, Any]],
    *,
    quality_similar_threshold: float,
    latency_regression_threshold: float,
    token_regression_threshold: float,
) -> list[dict[str, Any]]:
    baseline_item = next(
        (item for item in results if item["variant"] == "baseline"), None
    )
    baseline_summary = baseline_item["summary"] if baseline_item else {}
    active_quality_keys = (
        _active_quality_keys(baseline_summary)
        if baseline_item
        else ["score_contains_all", "score_forbidden_absent", "score_max_chars"]
    )
    baseline_quality = (
        _quality_score(baseline_summary, active_quality_keys) if baseline_item else 0.0
    )
    baseline_latency = _extract_mean(baseline_summary, "model_latency")
    baseline_tokens = _extract_mean(
        baseline_summary, "score_token_usage", "total_tokens"
    )

    ranked: list[dict[str, Any]] = []
    for result in results:
        summary = result["summary"]
        quality_score = _quality_score(summary, active_quality_keys)
        latency_mean = _extract_mean(summary, "model_latency")
        token_mean = _extract_mean(summary, "score_token_usage", "total_tokens")
        quality_delta = quality_score - baseline_quality

        gate_pass = True
        gate_reason = "baseline"
        if result["variant"] != "baseline":
            reasons: list[str] = []
            quality_similar = abs(quality_delta) <= quality_similar_threshold
            if quality_similar:
                if (
                    baseline_latency is not None
                    and latency_mean is not None
                    and latency_mean
                    > baseline_latency * (1 + latency_regression_threshold)
                ):
                    reasons.append("latency_regression")
                if (
                    baseline_tokens is not None
                    and token_mean is not None
                    and token_mean > baseline_tokens * (1 + token_regression_threshold)
                ):
                    reasons.append("token_regression")
            gate_pass = len(reasons) == 0
            gate_reason = ",".join(reasons) if reasons else "pass"

        ranked.append(
            {
                **result,
                "quality_score": quality_score,
                "quality_delta_vs_baseline": quality_delta,
                "latency_mean": latency_mean,
                "token_mean": token_mean,
                "gate_pass": gate_pass,
                "gate_reason": gate_reason,
            }
        )
    return sorted(ranked, key=lambda item: item["quality_score"], reverse=True)


def render_ranked_summary_table(ranked: list[dict[str, Any]]) -> str:
    lines = ["Ranking Summary:"]
    for idx, item in enumerate(ranked, start=1):
        summary = item["summary"]
        lines.extend(
            [
                f"{idx}. variant: {item['variant']}",
                f"   quality_score: {item['quality_score']:.3f}",
                f"   quality_delta_vs_baseline: {item['quality_delta_vs_baseline']:.3f}",
                f"   contains_pass: {_extract_true_fraction(summary, 'score_contains_all'):.3f}",
                f"   forbidden_pass: {_extract_true_fraction(summary, 'score_forbidden_absent'):.3f}",
                f"   max_chars_pass: {_extract_true_fraction(summary, 'score_max_chars'):.3f}",
                f"   json_pass: {_extract_true_fraction(summary, 'score_json_validity'):.3f}",
                f"   sections_pass: {_extract_true_fraction(summary, 'score_required_sections'):.3f}",
                f"   file_paths_pass: {_extract_true_fraction(summary, 'score_file_path_citations'):.3f}",
                f"   latency_mean: {item['latency_mean'] if item['latency_mean'] is not None else 'n/a'}",
                f"   total_tokens_mean: {item['token_mean'] if item['token_mean'] is not None else 'n/a'}",
                f"   gate_pass: {item['gate_pass']}",
                f"   gate_reason: {item['gate_reason']}",
            ]
        )
    return "\n".join(lines)


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

    variant_results: list[dict[str, Any]] = []
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
                timeout_seconds=args.timeout_seconds,
            )
            evaluation = weave.Evaluation(
                name=f"codex-doc-impact-{variant['name']}",
                dataset=cases,
                scorers=[
                    contains_all_scorer,
                    forbidden_absent_scorer,
                    max_chars_scorer,
                    json_validity_scorer,
                    required_sections_scorer,
                    file_path_citations_scorer,
                    token_usage_scorer,
                ],
            )
            result = asyncio.run(evaluation.evaluate(model))
            item = {"variant": variant["name"], "summary": result}
            variant_results.append(item)
            print(json.dumps(item, ensure_ascii=True))

    ranked = rank_variant_results(
        variant_results,
        quality_similar_threshold=args.quality_similar_threshold,
        latency_regression_threshold=args.latency_regression_threshold,
        token_regression_threshold=args.token_regression_threshold,
    )
    print(render_ranked_summary_table(ranked))

    failed_candidates = [
        item
        for item in ranked
        if item["variant"] != "baseline" and not item["gate_pass"]
    ]
    if failed_candidates:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
