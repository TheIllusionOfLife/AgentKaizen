from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import weave
from weave.trace.context import weave_client_context

from agentkaizen.core import ensure_wandb_api_key, resolve_weave_project

logger = logging.getLogger(__name__)


def build_case_from_call_output(
    call_output: dict[str, Any], max_chars_padding: int
) -> dict[str, Any]:
    prompt = str(call_output["prompt"])
    final_message = str(call_output.get("final_message", ""))
    max_chars = len(final_message) + max_chars_padding
    return {
        "prompt": prompt,
        "must_contain": [],
        "must_not_contain": [],
        "max_chars": max_chars,
        "require_json": False,
        "required_sections": [],
        "require_file_paths": False,
    }


def build_case_from_interactive_trace(
    trace_output: dict[str, Any], max_chars_padding: int
) -> dict[str, Any]:
    prompt = str(trace_output.get("user_task") or trace_output.get("thread_name", ""))
    summary = str(trace_output.get("analysis_summary", ""))
    max_chars = len(summary) + max_chars_padding
    return {
        "prompt": prompt,
        "must_contain": [],
        "must_not_contain": [],
        "max_chars": max_chars,
        "require_json": False,
        "required_sections": [],
        "require_file_paths": False,
        "source": "interactive",
    }


def redact_prompt(prompt: str, redact_patterns: list[str]) -> str:
    redacted = prompt
    for pattern in redact_patterns:
        redacted = re.sub(pattern, "[REDACTED]", redacted)
    return redacted


def deduplicate_cases_by_prompt(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for case in cases:
        prompt = case["prompt"]
        if prompt in seen:
            continue
        seen.add(prompt)
        deduped.append(case)
    return deduped


def load_cases_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


def write_cases_jsonl(path: Path, cases: list[dict[str, Any]]) -> None:
    lines = [json.dumps(case, ensure_ascii=True) for case in cases]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def fetch_recent_codex_cases(
    *,
    limit: int,
    op_substring: str,
    max_chars_padding: int,
    redact_patterns: list[str],
) -> list[dict[str, Any]]:
    client = weave_client_context.get_weave_client()
    cases: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()

    calls_iter = client.get_calls(
        limit=max(limit * 5, 50),
        sort_by=[{"field": "started_at", "direction": "desc"}],
    )

    for call in calls_iter:
        op_name = str(getattr(call, "op_name", ""))
        if op_substring not in op_name:
            continue

        output_obj = getattr(call, "output", None)
        try:
            output = dict(output_obj) if output_obj is not None else {}
        except (TypeError, ValueError):
            metadata: dict[str, Any] = {
                "output_type": type(output_obj).__name__,
            }
            if isinstance(output_obj, Mapping):
                metadata["key_count"] = len(output_obj)
                metadata["keys"] = sorted(str(key) for key in output_obj.keys())
            elif hasattr(output_obj, "__len__"):
                try:
                    metadata["size"] = len(output_obj)  # type: ignore[arg-type]
                except TypeError:
                    pass
            logger.warning(
                "Skipping call with non-dict output payload: op_name=%s metadata=%s",
                op_name,
                metadata,
            )
            continue

        if not isinstance(output, dict):
            continue
        if output.get("returncode") != 0:
            continue
        if "prompt" not in output:
            continue

        case = build_case_from_call_output(output, max_chars_padding=max_chars_padding)
        case["prompt"] = redact_prompt(case["prompt"], redact_patterns)
        if case["prompt"] in seen_prompts:
            continue
        seen_prompts.add(case["prompt"])
        cases.append(case)
        if len(cases) >= limit:
            break

    return cases[:limit]


def fetch_recent_interactive_cases(
    *,
    limit: int,
    op_substring: str,
    max_chars_padding: int,
    redact_patterns: list[str],
) -> list[dict[str, Any]]:
    client = weave_client_context.get_weave_client()
    cases: list[dict[str, Any]] = []
    seen_prompts: set[str] = set()

    calls_iter = client.get_calls(
        limit=max(limit * 5, 50),
        sort_by=[{"field": "started_at", "direction": "desc"}],
    )

    for call in calls_iter:
        op_name = str(getattr(call, "op_name", ""))
        if op_substring not in op_name:
            continue

        output_obj = getattr(call, "output", None)
        try:
            output = dict(output_obj) if output_obj is not None else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(output, dict):
            continue
        if output.get("source") != "codex_interactive":
            continue

        case = build_case_from_interactive_trace(
            output, max_chars_padding=max_chars_padding
        )
        case["prompt"] = redact_prompt(case["prompt"], redact_patterns)
        if case["prompt"] in seen_prompts:
            continue
        seen_prompts.add(case["prompt"])
        cases.append(case)
        if len(cases) >= limit:
            break

    return cases[:limit]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate eval cases from recent Weave codex traces"
    )
    parser.add_argument("--entity", help="W&B entity/team")
    parser.add_argument("--project", help="W&B project")
    parser.add_argument("--limit", type=int, default=20, help="Max cases to generate")
    parser.add_argument(
        "--output",
        default="evals/cases.generated.jsonl",
        help="Output JSONL file",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing output file (dedupe by prompt)",
    )
    parser.add_argument(
        "--max-chars-padding",
        type=int,
        default=20,
        help="Padding added to observed output length when generating max_chars",
    )
    parser.add_argument(
        "--op-substring",
        default="run_codex_exec_traced",
        help="Only use calls whose op_name contains this value",
    )
    parser.add_argument(
        "--include-interactive",
        action="store_true",
        help="Also generate draft cases from interactive session traces",
    )
    parser.add_argument(
        "--interactive-op-substring",
        default="ingest_interactive_session_traced",
        help="Only use interactive calls whose op_name contains this value",
    )
    parser.add_argument(
        "--redact-regex",
        action="append",
        default=[],
        help="Regex pattern to redact from prompts before writing cases (repeatable)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not ensure_wandb_api_key():
        print("WANDB_API_KEY is required to generate cases.", file=sys.stderr)
        return 2
    try:
        project_path = resolve_weave_project(args.entity, args.project)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    weave.init(project_path)

    new_cases = fetch_recent_codex_cases(
        limit=args.limit,
        op_substring=args.op_substring,
        max_chars_padding=args.max_chars_padding,
        redact_patterns=args.redact_regex,
    )
    if args.include_interactive:
        interactive_cases = fetch_recent_interactive_cases(
            limit=args.limit,
            op_substring=args.interactive_op_substring,
            max_chars_padding=args.max_chars_padding,
            redact_patterns=args.redact_regex,
        )
        new_cases = deduplicate_cases_by_prompt([*new_cases, *interactive_cases])[
            : args.limit
        ]

    out_path = Path(args.output).expanduser().resolve()
    if args.append:
        existing = load_cases_jsonl(out_path)
        merged = deduplicate_cases_by_prompt([*existing, *new_cases])
        write_cases_jsonl(out_path, merged)
        print(
            json.dumps(
                {
                    "generated": len(new_cases),
                    "existing": len(existing),
                    "written": len(merged),
                    "output": str(out_path),
                },
                ensure_ascii=True,
            )
        )
    else:
        write_cases_jsonl(out_path, new_cases)
        print(
            json.dumps(
                {
                    "generated": len(new_cases),
                    "written": len(new_cases),
                    "output": str(out_path),
                },
                ensure_ascii=True,
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
