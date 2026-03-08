from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
import subprocess  # noqa: F401  (re-exported for test patchability)
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from agentkaizen._llm_judge import LLMJudgeScorer
from agentkaizen._weave_compat import HAS_WEAVE, weave_init, weave_op

from agentkaizen._local_eval import (
    LocalEvaluation,
    LocalModel,
    LocalPydanticScorer,
    LocalScorer,
    LocalValidJSONScorer,
)

if HAS_WEAVE:
    import weave

    try:
        from weave.scorers import PydanticScorer, ValidJSONScorer

        HAS_WEAVE_SCORERS = True
    except ImportError:
        HAS_WEAVE_SCORERS = False  # weave installed without [scorers] extras
else:
    HAS_WEAVE_SCORERS = False

from agentkaizen.runners import get_runner
from agentkaizen.runners.base import AgentRunError
from agentkaizen.core import (
    ensure_wandb_api_key,
    resolve_weave_project,
)
from agentkaizen.scoring import (
    score_contains_all,
    score_exact_match,
    score_file_path_citations,
    score_forbidden_absent,
    score_json_validity,
    score_max_chars,
    score_min_chars,
    score_required_content_groups,
    score_required_sections,
    score_token_usage,
)


class CaseLoadError(ValueError):
    pass


_SCHEMA_MODEL_CACHE: dict[str, type[BaseModel]] = {}
OPTIONAL_CASE_FIELDS = ("response_schema", "min_chars")


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
            if not isinstance(row, dict):
                raise CaseLoadError(
                    f"Non-object JSON in {case_path.name} at line {line_number}: got {type(row).__name__}"
                ) from None
            if "suite" not in row:
                row["suite"] = case_path.stem
            rows.append(row)
    present_optional_fields = {
        field_name
        for field_name in OPTIONAL_CASE_FIELDS
        if any(field_name in row for row in rows)
    }
    for row in rows:
        for field_name in present_optional_fields:
            row.setdefault(field_name, None)
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


if HAS_WEAVE_SCORERS:
    contains_all_scorer = weave.op()(score_contains_all)
    forbidden_absent_scorer = weave.op()(score_forbidden_absent)
    exact_match_scorer = weave.op()(score_exact_match)
    max_chars_scorer = weave.op()(score_max_chars)
    min_chars_scorer = weave.op()(score_min_chars)
    json_validity_scorer = weave.op()(score_json_validity)
    required_sections_scorer = weave.op()(score_required_sections)
    required_content_groups_scorer = weave.op()(score_required_content_groups)
    file_path_citations_scorer = weave.op()(score_file_path_citations)
    token_usage_scorer = weave.op()(score_token_usage)
else:
    contains_all_scorer = score_contains_all
    forbidden_absent_scorer = score_forbidden_absent
    exact_match_scorer = score_exact_match
    max_chars_scorer = score_max_chars
    min_chars_scorer = score_min_chars
    json_validity_scorer = score_json_validity
    required_sections_scorer = score_required_sections
    required_content_groups_scorer = score_required_content_groups
    file_path_citations_scorer = score_file_path_citations
    token_usage_scorer = score_token_usage


def _extract_output_text(output: str | dict[str, Any]) -> str:
    if isinstance(output, dict):
        value = output.get("text", "")
        return value if isinstance(value, str) else str(value)
    return output


def _json_schema_to_python_type(
    schema: dict[str, Any], model_name: str
) -> type[Any] | Any:
    schema_type = schema.get("type", "string")
    if isinstance(schema_type, list):
        types = [item for item in schema_type if item != "null"]
        base_type = (
            _json_schema_to_python_type({**schema, "type": types[0]}, model_name)
            if types
            else Any
        )
        return base_type | None
    if schema_type == "object":
        return _pydantic_model_from_json_schema(schema, model_name=model_name)
    if schema_type == "array":
        item_schema = schema.get("items", {})
        if not isinstance(item_schema, dict):
            item_schema = {}
        return list[_json_schema_to_python_type(item_schema, f"{model_name}Item")]
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    return str


def _pydantic_model_from_json_schema(
    schema: dict[str, Any], *, model_name: str = "EvalResponse"
) -> type[BaseModel]:
    cache_key = json.dumps(schema, sort_keys=True)
    cached = _SCHEMA_MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required", [])
    if not isinstance(required, list):
        required = []
    required_fields = {str(item) for item in required}
    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, field_schema in properties.items():
        normalized_schema = field_schema if isinstance(field_schema, dict) else {}
        annotation = _json_schema_to_python_type(
            normalized_schema, f"{model_name}{str(field_name).title()}"
        )
        if field_name in required_fields:
            fields[str(field_name)] = (annotation, ...)
        else:
            fields[str(field_name)] = (annotation | None, None)

    model = create_model(
        model_name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    _SCHEMA_MODEL_CACHE[cache_key] = model
    return model


if HAS_WEAVE_SCORERS:

    class BuiltinValidJSONCaseScorer(weave.Scorer):
        name: str = "builtin_json_validity"
        column_map: dict[str, str] | None = {"response_schema": "response_schema"}

        @weave.op()
        def score(
            self,
            *,
            output: str | dict[str, Any],
            require_json: bool = False,
            response_schema: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            del require_json
            if response_schema is None:
                return {"pass": None, "applicable": False, "json_valid": None}
            result = ValidJSONScorer().score(output=_extract_output_text(output))
            json_valid = bool(result.get("json_valid"))
            return {"pass": json_valid, "applicable": True, "json_valid": json_valid}

    class BuiltinPydanticCaseScorer(weave.Scorer):
        name: str = "builtin_pydantic"
        column_map: dict[str, str] | None = {"response_schema": "response_schema"}

        @weave.op()
        def score(
            self,
            *,
            output: str | dict[str, Any],
            response_schema: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            if response_schema is None:
                return {"pass": None, "applicable": False, "valid_pydantic": None}
            model = _pydantic_model_from_json_schema(response_schema)
            result = PydanticScorer(model=model).score(
                output=_extract_output_text(output)
            )
            valid_pydantic = bool(result.get("valid_pydantic"))
            return {
                "pass": valid_pydantic,
                "applicable": True,
                "valid_pydantic": valid_pydantic,
            }

else:

    class BuiltinValidJSONCaseScorer(LocalScorer):  # type: ignore[no-redef]
        name: str = "builtin_json_validity"
        column_map = {"response_schema": "response_schema"}

        def score(
            self,
            *,
            output: str | dict[str, Any],
            require_json: bool = False,
            response_schema: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            del require_json
            if response_schema is None:
                return {"pass": None, "applicable": False, "json_valid": None}
            result = LocalValidJSONScorer().score(output=_extract_output_text(output))
            json_valid = bool(result.get("json_valid"))
            return {"pass": json_valid, "applicable": True, "json_valid": json_valid}

    class BuiltinPydanticCaseScorer(LocalScorer):  # type: ignore[no-redef]
        name: str = "builtin_pydantic"
        column_map = {"response_schema": "response_schema"}

        def score(
            self,
            *,
            output: str | dict[str, Any],
            response_schema: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            if response_schema is None:
                return {"pass": None, "applicable": False, "valid_pydantic": None}
            pydantic_model = _pydantic_model_from_json_schema(response_schema)
            result = LocalPydanticScorer(model=pydantic_model).score(
                output=_extract_output_text(output)
            )
            valid_pydantic = bool(result.get("valid_pydantic"))
            return {
                "pass": valid_pydantic,
                "applicable": True,
                "valid_pydantic": valid_pydantic,
            }


def _dataset_has_field(cases: list[dict[str, Any]], field_name: str) -> bool:
    return any(field_name in case for case in cases)


def build_eval_scorers(cases: list[dict[str, Any]] | None = None) -> list[Any]:
    dataset = cases or []
    scorers: list[Any] = [
        contains_all_scorer,
        forbidden_absent_scorer,
        exact_match_scorer,
        max_chars_scorer,
        json_validity_scorer,
        required_sections_scorer,
        required_content_groups_scorer,
        file_path_citations_scorer,
        token_usage_scorer,
    ]
    if _dataset_has_field(dataset, "min_chars"):
        scorers.append(min_chars_scorer)
    if _dataset_has_field(dataset, "response_schema"):
        scorers.extend(
            [
                BuiltinValidJSONCaseScorer(),
                BuiltinPydanticCaseScorer(),
            ]
        )
    return scorers


def normalize_codex_args(codex_args: list[str]) -> list[str]:
    if "--skip-git-repo-check" in codex_args:
        return codex_args
    return [*codex_args, "--skip-git-repo-check"]


_ModelBase = weave.Model if HAS_WEAVE else LocalModel


class CodexVariantModel(_ModelBase):
    workspace: str
    codex_model: str | None = None
    sandbox: str | None = None
    profile: str | None = None
    codex_args: list[str] = []
    timeout_seconds: int = 300

    @weave_op()
    def predict(self, prompt: str) -> dict[str, Any]:
        runner = get_runner(
            "codex",
            model=self.codex_model,
            sandbox=self.sandbox,
            profile=self.profile,
            extra_args=normalize_codex_args(self.codex_args),
            skip_git_repo_check=False,  # already in normalize_codex_args
        )
        try:
            result = runner.run(
                prompt,
                workspace=Path(self.workspace),
                timeout_seconds=self.timeout_seconds,
            )
        except AgentRunError as exc:
            raise RuntimeError(str(exc)) from exc
        if result.returncode != 0:
            raise RuntimeError(
                f"codex exec failed (exit={result.returncode}): {result.stderr.strip()}"
            )
        return {"text": result.final_message, "usage": vars(result.usage)}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Weave Evals for Codex using document variants"
    )
    parser.add_argument(
        "--cases",
        default=None,
        help="Path to a JSONL evaluation file or directory of JSONL case suites (default: evals/cases)",
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
        default=None,
        help="Timeout for each codex exec call in seconds (default: 300)",
    )
    parser.add_argument(
        "--show-outputs",
        action="store_true",
        default=False,
        help="Show actual response text and per-case scorer results",
    )
    parser.add_argument(
        "--edit",
        action="append",
        default=[],
        metavar="PATH:MODE:TEXT",
        help="Inline variant file edit (repeatable). Format: PATH:MODE:TEXT where MODE is append|prepend|replace",
    )
    parser.add_argument(
        "--variant-name",
        default="custom",
        help="Name for the inline variant created by --edit (default: custom)",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=[],
        dest="inline_prompts",
        help="Inline eval case prompt (repeatable). Chain with --must-contain / --max-chars etc.",
    )
    parser.add_argument(
        "--must-contain",
        action="append",
        default=[],
        help="must_contain term for the preceding --prompt (repeatable)",
    )
    parser.add_argument(
        "--must-not-contain",
        action="append",
        default=[],
        help="must_not_contain term for the preceding --prompt (repeatable)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="max_chars for the preceding --prompt",
    )
    parser.add_argument(
        "--judge-rubric",
        default=None,
        help="Global LLM-judge rubric (per-case judge_rubric field overrides)",
    )
    parser.add_argument(
        "--judge-runner",
        default="claude-code",
        help="Runner for LLM judge: claude-code|codex (default: claude-code)",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Model for judge runner",
    )
    parser.add_argument(
        "--allow-unsafe-scorer-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Load scorers from Python file (explicit unsafe opt-in; file must define SCORERS list)",
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

        applicable_summary = scorer_summary.get("applicable", {})
        if isinstance(applicable_summary, dict) and (
            "true_fraction" in applicable_summary
            or "count" in applicable_summary
            or "true_count" in applicable_summary
            or "false_count" in applicable_summary
        ):
            applicable_fraction = float(
                applicable_summary.get("true_fraction", 0.0) or 0.0
            )
            applicable_count = _count_from_stats(applicable_summary) or row_count
            if applicable_count > 0:
                return applicable_fraction * applicable_count

        exact_match_summary = scorer_summary.get("exact_match_required", {})
        if isinstance(exact_match_summary, dict) and (
            "true_fraction" in exact_match_summary
            or "count" in exact_match_summary
            or "true_count" in exact_match_summary
            or "false_count" in exact_match_summary
        ):
            exact_match_fraction = float(
                exact_match_summary.get("true_fraction", 0.0) or 0.0
            )
            exact_match_count = _count_from_stats(exact_match_summary) or row_count
            if exact_match_count > 0:
                return exact_match_fraction * exact_match_count

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

    min_chars_required = _extract_mean(summary, "score_min_chars", "min_chars") or 0.0
    if min_chars_required > 0.0:
        keys.append("score_min_chars")

    exact_match_required = float(
        summary.get("score_exact_match", {})
        .get("exact_match_required", {})
        .get("true_fraction", 0.0)
        or 0.0
    )
    if exact_match_required > 0.0:
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

    required_group_mean = float(
        summary.get("score_required_content_groups", {})
        .get("required_group_count", {})
        .get("mean", 0.0)
        or 0.0
    )
    if required_group_mean > 0.0:
        keys.append("score_required_content_groups")

    require_paths_fraction = float(
        summary.get("score_file_path_citations", {})
        .get("require_file_paths", {})
        .get("true_fraction", 0.0)
        or 0.0
    )
    if require_paths_fraction > 0.0:
        keys.append("score_file_path_citations")

    builtin_json_fraction = float(
        summary.get("builtin_json_validity", {})
        .get("applicable", {})
        .get("true_fraction", 0.0)
        or 0.0
    )
    if builtin_json_fraction > 0.0:
        keys.append("builtin_json_validity")

    builtin_pydantic_fraction = float(
        summary.get("builtin_pydantic", {})
        .get("applicable", {})
        .get("true_fraction", 0.0)
        or 0.0
    )
    if builtin_pydantic_fraction > 0.0:
        keys.append("builtin_pydantic")

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
                f"   min_chars_pass: {_extract_true_fraction(summary, 'score_min_chars'):.3f}",
                f"   json_pass: {_extract_true_fraction(summary, 'score_json_validity'):.3f}",
                f"   builtin_json_pass: {_extract_true_fraction(summary, 'builtin_json_validity'):.3f}",
                f"   schema_pass: {_extract_true_fraction(summary, 'builtin_pydantic'):.3f}",
                f"   sections_pass: {_extract_true_fraction(summary, 'score_required_sections'):.3f}",
                f"   content_groups_pass: {_extract_true_fraction(summary, 'score_required_content_groups'):.3f}",
                f"   file_paths_pass: {_extract_true_fraction(summary, 'score_file_path_citations'):.3f}",
                f"   latency_mean: {item['latency_mean'] if item['latency_mean'] is not None else 'n/a'}",
                f"   total_tokens_mean: {item['token_mean'] if item['token_mean'] is not None else 'n/a'}",
                f"   gate_pass: {item['gate_pass']}",
                f"   gate_reason: {item['gate_reason']}",
            ]
        )
    return "\n".join(lines)


_VALID_EDIT_MODES = {"append", "prepend", "replace"}


def _parse_edit_flag(raw: str) -> dict[str, str]:
    parts = raw.split(":", 2)
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(
            f"--edit must be PATH:MODE or PATH:MODE:TEXT (got {raw!r})"
        )
    path, mode = parts[0], parts[1]
    if mode not in _VALID_EDIT_MODES:
        raise argparse.ArgumentTypeError(
            f"--edit mode must be one of {sorted(_VALID_EDIT_MODES)} (got {mode!r})"
        )
    return {"path": path, "mode": mode, "text": parts[2] if len(parts) > 2 else ""}


def _build_inline_cases(argv: list[str]) -> list[dict[str, Any]]:
    """Parse argv to group --must-contain / --must-not-contain / --max-chars by --prompt."""
    cases: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--prompt" and i + 1 < len(argv):
            if current is not None:
                cases.append(current)
            i += 1
            current = {
                "prompt": argv[i],
                "must_contain": [],
                "must_not_contain": [],
                "max_chars": 2000,
                "require_json": False,
                "required_sections": [],
                "require_file_paths": False,
            }
        elif arg == "--must-contain" and i + 1 < len(argv) and current is not None:
            i += 1
            current["must_contain"].append(argv[i])
        elif arg == "--must-not-contain" and i + 1 < len(argv) and current is not None:
            i += 1
            current["must_not_contain"].append(argv[i])
        elif arg == "--max-chars" and i + 1 < len(argv) and current is not None:
            i += 1
            try:
                current["max_chars"] = int(argv[i])
            except ValueError:
                raise argparse.ArgumentTypeError(
                    f"--max-chars requires an integer (got {argv[i]!r})"
                )
        i += 1
    if current is not None:
        cases.append(current)
    return cases


def _load_scorer_file(path: str) -> list[Any]:
    """Load SCORERS list from a Python file (explicit unsafe opt-in)."""
    spec = importlib.util.spec_from_file_location("_user_scorers", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load scorer file: {path!r}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    scorers = getattr(mod, "SCORERS", None)
    if scorers is None:
        raise ValueError(f"scorer file {path!r} must define a top-level SCORERS list")
    return list(scorers)


_COL_WIDTH = 42


def _format_scorer_value(name: str, value: Any) -> str:
    if isinstance(value, dict):
        pass_val = value.get("pass")
        score_val = value.get("score")
        reasoning = value.get("reasoning", "")
        if score_val is not None:
            icon = "✅" if pass_val else ("❌" if pass_val is False else "—")
            snippet = str(reasoning)[:30] if reasoning else ""
            return f"{name}: {score_val:.2f} {icon} {snippet}".rstrip()
        if pass_val is True:
            return f"{name}: ✅ PASS"
        if pass_val is False:
            return f"{name}: ❌ FAIL"
        if pass_val is None:
            return f"{name}: — N/A"
    return f"{name}: {value}"


def render_per_case_comparison(
    variant_names: list[str],
    per_case_by_variant: dict[str, list[dict[str, Any]]],
    cases: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    n_cases = len(cases)
    for idx in range(n_cases):
        prompt = cases[idx].get("prompt", "")
        prompt_snippet = prompt[:60] + ("..." if len(prompt) > 60 else "")
        lines.append(f"\n=== Case {idx + 1}/{n_cases}: {prompt_snippet!r} ===\n")

        # Build per-variant output and scorer rows
        col_data: list[dict[str, Any]] = []
        for vname in variant_names:
            vcases = per_case_by_variant.get(vname, [])
            if idx < len(vcases):
                col_data.append(vcases[idx])
            else:
                col_data.append({"output": "", "scorer_results": {}})

        # Header row
        headers = []
        for i, vname in enumerate(variant_names):
            label = "BASELINE" if i == 0 else f"VARIANT: {vname}"
            headers.append(label.ljust(_COL_WIDTH))
        lines.append("   ".join(headers))
        lines.append(("─" * _COL_WIDTH + "   ") * len(variant_names))

        # Output text rows
        output_lines: list[list[str]] = []
        for entry in col_data:
            text = entry.get("output", "")
            char_count = len(text)
            wrapped = textwrap.wrap(text, _COL_WIDTH - 2) or [""]
            wrapped[-1] = wrapped[-1] + f" ({char_count} chars)"
            output_lines.append(wrapped)

        max_rows = max((len(ols) for ols in output_lines), default=0)
        for row_i in range(max_rows):
            row_cells = []
            for ols in output_lines:
                cell = ols[row_i] if row_i < len(ols) else ""
                row_cells.append(cell.ljust(_COL_WIDTH))
            lines.append("   ".join(row_cells))

        lines.append("")

        # Scorer rows
        all_scorer_keys: list[str] = []
        seen: set[str] = set()
        for entry in col_data:
            for k in entry.get("scorer_results", {}):
                if k not in seen:
                    all_scorer_keys.append(k)
                    seen.add(k)

        for skey in all_scorer_keys:
            row_cells = []
            for entry in col_data:
                val = entry.get("scorer_results", {}).get(skey)
                cell = "  " + _format_scorer_value(skey, val)
                row_cells.append(cell.ljust(_COL_WIDTH))
            lines.append("   ".join(row_cells))

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from agentkaizen.config import load_config, merge_cli_args

    raw_argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(raw_argv)

    # Validate --edit flags early
    inline_edits: list[dict[str, str]] = []
    for raw_edit in args.edit:
        try:
            inline_edits.append(_parse_edit_flag(raw_edit))
        except argparse.ArgumentTypeError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    config = load_config()
    config = merge_cli_args(config, args)

    tracing_enabled = HAS_WEAVE and bool(ensure_wandb_api_key())

    # If --judge-rubric is given, force local eval path before resolving project
    if args.judge_rubric and HAS_WEAVE_SCORERS and tracing_enabled:
        print(
            "info: --judge-rubric forces local eval path (Weave scorers disabled for this run).",
            file=sys.stderr,
        )
        tracing_enabled = False

    if tracing_enabled:
        try:
            project_path = resolve_weave_project(config.entity, config.project)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        if not HAS_WEAVE:
            print(
                "info: weave not installed — running in local-only mode.",
                file=sys.stderr,
            )
        elif not ensure_wandb_api_key():
            print(
                "info: WANDB_API_KEY not set — running in local-only mode.",
                file=sys.stderr,
            )

    repo_root = Path.cwd()

    # Build cases: file-based and/or inline
    inline_cases = _build_inline_cases(raw_argv)
    explicit_cases_path = args.cases  # None when --cases was not passed
    if explicit_cases_path is not None:
        try:
            file_cases = load_cases_jsonl(Path(explicit_cases_path))
        except CaseLoadError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        cases = file_cases + inline_cases
    elif inline_cases:
        cases = inline_cases
    else:
        # Fall back to configured/default path
        try:
            cases = load_cases_jsonl(Path(config.cases))
        except CaseLoadError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    # Re-check judge need now that we have cases
    needs_judge = bool(args.judge_rubric) or any("judge_rubric" in c for c in cases)
    if needs_judge and HAS_WEAVE_SCORERS and tracing_enabled:
        print(
            "info: --judge-rubric forces local eval path (Weave scorers disabled for this run).",
            file=sys.stderr,
        )
        tracing_enabled = False

    if tracing_enabled:
        weave_init(project_path)

    # Build variants: file-based (includes baseline) + optional inline
    try:
        variants = _variants_from_args(args.variant_file)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if inline_edits:
        inline_variant: dict[str, Any] = {
            "name": args.variant_name or "custom",
            "edits": inline_edits,
        }
        # Insert inline variant right after baseline
        variants.insert(1, inline_variant)

    # Load custom scorers
    extra_scorers: list[Any] = []
    for scorer_path in args.allow_unsafe_scorer_file:
        try:
            extra_scorers.extend(_load_scorer_file(scorer_path))
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 2

    # Inject LLM judge
    if needs_judge:
        extra_scorers.append(
            LLMJudgeScorer(
                rubric=args.judge_rubric or "",
                runner_name=args.judge_runner,
                model=args.judge_model,
            )
        )

    scorers = [*build_eval_scorers(cases), *extra_scorers]

    per_case_by_variant: dict[str, list[dict[str, Any]]] = {}
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
                    "model": config.model,
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
                timeout_seconds=config.timeout_seconds,
            )
            if HAS_WEAVE_SCORERS and tracing_enabled:
                evaluation = weave.Evaluation(
                    name=f"codex-doc-impact-{variant['name']}",
                    dataset=cases,
                    scorers=scorers,
                )
                result = asyncio.run(evaluation.evaluate(model))
                # Weave path has no per_case_results
                per_case_by_variant[variant["name"]] = []
            else:
                evaluation = LocalEvaluation(
                    name=f"codex-doc-impact-{variant['name']}",
                    dataset=cases,
                    scorers=scorers,
                )
                result = evaluation.evaluate(model)
                per_case_by_variant[variant["name"]] = evaluation.per_case_results
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

    if args.show_outputs:
        variant_names = [v["name"] for v in variants]
        weave_path_used = HAS_WEAVE_SCORERS and tracing_enabled
        if weave_path_used:
            print(
                "info: --show-outputs not available with Weave path; "
                "unset WANDB_API_KEY to force local.",
                file=sys.stderr,
            )
        else:
            print(render_per_case_comparison(variant_names, per_case_by_variant, cases))

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
