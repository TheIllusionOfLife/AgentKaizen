from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import weave

from codex_scoring import (
    score_contains_all,
    score_exact_match,
    score_file_path_citations,
    score_forbidden_absent,
    score_json_validity,
    score_max_chars,
    score_required_sections,
    score_token_usage,
)
from codex_weave import (
    ensure_wandb_api_key,
    parse_codex_jsonl,
    resolve_weave_project,
)


class CaseLoadError(ValueError):
    pass


def load_cases_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise CaseLoadError(f"Case path not found: {path}")

    rows: list[dict[str, Any]] = []
    if path.is_dir():
        paths = sorted(path.glob("*.jsonl"))
        if not paths:
            raise CaseLoadError(f"No JSONL case files found in directory: {path}")
    elif path.is_file():
        paths = [path]
    else:
        raise CaseLoadError(f"Unsupported case path: {path}")

    for case_path in paths:
        for line_number, line in enumerate(
            case_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise CaseLoadError(
                    f"Malformed JSON in {case_path.name} at line {line_number}: {exc.msg}"
                ) from exc
            if isinstance(row, dict) and "suite" not in row:
                row["suite"] = case_path.stem
            rows.append(row)
    return rows


def load_variant_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _variant_file_edits(variant: dict[str, Any]) -> list[dict[str, Any]]:
    file_edits = variant.get("file_edits")
    if "file_edits" in variant:
        if not isinstance(file_edits, list):
            raise TypeError("variant.file_edits must be a list")
        return file_edits
    edits = variant.get("edits", [])
    normalized: list[dict[str, Any]] = []
    for edit in edits:
        normalized.append({"source_scope": "repo", **edit})
    return normalized


def materialize_external_variant_inputs(
    workspace: Path, variant: dict[str, Any]
) -> dict[str, Path]:
    external_files = variant.get("external_files", [])
    mapping: dict[str, Path] = {}
    workspace_resolved = workspace.resolve()
    for item in external_files:
        source = Path(item["source"]).expanduser().resolve()
        target_rel = Path(item["target"])
        if target_rel.is_absolute():
            raise ValueError(f"External target path must be relative: {target_rel}")
        target = (workspace_resolved / target_rel).resolve()
        if not target.is_relative_to(workspace_resolved):
            raise ValueError(f"External target path escapes workspace: {target_rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        mapping[str(source)] = target_rel
    return mapping


def apply_variant_edits(
    workspace: Path,
    variant: dict[str, Any],
    *,
    external_path_map: dict[str, Path] | None = None,
) -> None:
    edits = _variant_file_edits(variant)
    workspace_resolved = workspace.resolve()
    for edit in edits:
        source_scope = str(edit.get("source_scope", "repo"))
        if source_scope == "external":
            if external_path_map is None:
                raise ValueError("External edits require an external_path_map.")
            mapped_path = external_path_map.get(
                str(Path(edit["path"]).expanduser().resolve())
            )
            if mapped_path is None:
                raise ValueError(
                    f"External edit target not materialized: {edit['path']}"
                )
            rel_path = mapped_path
        elif source_scope == "repo":
            rel_path = Path(edit["path"])
        else:
            raise ValueError(f"Unsupported source_scope: {source_scope}")
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


def resolve_variant_codex_config(
    *, variant: dict[str, Any], cli_args: dict[str, Any]
) -> dict[str, Any]:
    variant_config = variant.get("codex_config", {})
    if not isinstance(variant_config, dict):
        variant_config = {}
    raw_codex_args = variant_config.get("codex_args", cli_args.get("codex_args", []))
    if raw_codex_args is None:
        codex_args: list[str] = []
    elif not isinstance(raw_codex_args, list) or not all(
        isinstance(arg, str) for arg in raw_codex_args
    ):
        raise ValueError("codex_config.codex_args must be a list of strings")
    else:
        codex_args = list(raw_codex_args)
    return {
        "model": variant_config.get("model", cli_args.get("model")),
        "sandbox": variant_config.get("sandbox", cli_args.get("sandbox")),
        "profile": variant_config.get("profile", cli_args.get("profile")),
        "codex_args": codex_args,
    }


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
exact_match_scorer = weave.op()(score_exact_match)
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
        default="evals/cases",
        help="Path to a JSONL evaluation file or directory of JSONL case suites",
    )
    parser.add_argument(
        "--variant-file",
        action="append",
        default=[],
        help="Path to variant JSON (repeatable)",
    )
    parser.add_argument("--entity", help="W&B entity/team")
    parser.add_argument("--project", help="W&B project")
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
    def _count_from_stats(stats: Any) -> float | None:
        if not isinstance(stats, dict):
            return None
        count = stats.get("count")
        if isinstance(count, (int, float)):
            return float(count)
        true_count = stats.get("true_count")
        false_count = stats.get("false_count")
        if isinstance(true_count, (int, float)) and isinstance(
            false_count, (int, float)
        ):
            return float(true_count + false_count)
        return None

    def _total_rows() -> float:
        for key in quality_keys:
            scorer_summary = summary.get(key, {})
            if not isinstance(scorer_summary, dict):
                continue
            pass_count = _count_from_stats(scorer_summary.get("pass", {}))
            if pass_count is not None and pass_count > 0:
                return pass_count
        return 1.0

    def _applicable_count(key: str, row_count: float) -> float:
        scorer_summary = summary.get(key, {})
        if not isinstance(scorer_summary, dict):
            return row_count

        applicable = scorer_summary.get("applicable_count")
        if isinstance(applicable, (int, float)):
            return float(applicable)

        if key == "score_json_validity":
            require_summary = scorer_summary.get("require_json", {})
            require_fraction = float(
                require_summary.get("true_fraction", 0.0)
                if isinstance(require_summary, dict)
                else 0.0
            )
            require_count = _count_from_stats(require_summary) or row_count
            return require_fraction * require_count

        if key == "score_file_path_citations":
            require_summary = scorer_summary.get("require_file_paths", {})
            require_fraction = float(
                require_summary.get("true_fraction", 0.0)
                if isinstance(require_summary, dict)
                else 0.0
            )
            require_count = _count_from_stats(require_summary) or row_count
            return require_fraction * require_count

        if key == "score_required_sections":
            required_summary = scorer_summary.get("required_count", {})
            required_count = _count_from_stats(required_summary)
            if required_count is not None:
                return required_count

        pass_count = _count_from_stats(scorer_summary.get("pass", {}))
        return pass_count if pass_count is not None else row_count

    row_count = _total_rows()
    weighted_passes = 0.0
    total_applicable = 0.0

    for key in quality_keys:
        applicable_count = _applicable_count(key, row_count)
        if applicable_count <= 0:
            continue
        pass_fraction = _extract_true_fraction(summary, key)
        weighted_passes += pass_fraction * applicable_count
        total_applicable += applicable_count

    if total_applicable == 0:
        return 0.0
    return weighted_passes / total_applicable


def _active_quality_keys(summary: dict[str, Any]) -> list[str]:
    keys = ["score_contains_all", "score_forbidden_absent", "score_max_chars"]

    exact_match_required = summary.get("score_exact_match", {}).get("exact_match")
    if exact_match_required is not None:
        keys.append("score_exact_match")

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
        else [
            "score_contains_all",
            "score_forbidden_absent",
            "score_exact_match",
            "score_max_chars",
        ]
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
                f"   exact_match_pass: {_extract_true_fraction(summary, 'score_exact_match'):.3f}",
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
        print("WANDB_API_KEY is required to run evals.", file=sys.stderr)
        return 2
    try:
        project_path = resolve_weave_project(args.entity, args.project)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    repo_root = Path.cwd()
    try:
        cases = load_cases_jsonl(Path(args.cases))
    except CaseLoadError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    weave.init(project_path)
    variants = _variants_from_args(args.variant_file)

    variant_results: list[dict[str, Any]] = []
    for variant in variants:
        with tempfile.TemporaryDirectory(prefix="codex-eval-") as td:
            temp_workspace = Path(td) / "workspace"
            copy_workspace(repo_root, temp_workspace)
            external_path_map = materialize_external_variant_inputs(
                temp_workspace, variant
            )
            apply_variant_edits(
                temp_workspace,
                variant,
                external_path_map=external_path_map,
            )
            resolved_config = resolve_variant_codex_config(
                variant=variant,
                cli_args={
                    "model": args.model,
                    "sandbox": args.sandbox,
                    "profile": args.profile,
                    "codex_args": args.codex_arg,
                },
            )

            model = CodexVariantModel(
                workspace=str(temp_workspace),
                codex_model=resolved_config["model"],
                sandbox=resolved_config["sandbox"],
                profile=resolved_config["profile"],
                codex_args=resolved_config["codex_args"],
                timeout_seconds=args.timeout_seconds,
            )
            evaluation = weave.Evaluation(
                name=f"codex-doc-impact-{variant['name']}",
                dataset=cases,
                scorers=[
                    contains_all_scorer,
                    forbidden_absent_scorer,
                    exact_match_scorer,
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
