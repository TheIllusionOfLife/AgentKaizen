from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

import weave

from codex_weave import DEFAULT_ENTITY, DEFAULT_PROJECT, ensure_wandb_api_key

ALLOWED_RELEVANCE = {"agents", "readme", "skill", "config", "none"}


def score_interactive_heuristics(trace: dict[str, Any]) -> dict[str, Any]:
    analysis = trace.get("analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}
    workflow_signals = [
        bool(analysis.get("branch_created")),
        bool(analysis.get("used_uv")),
        bool(analysis.get("ran_tests")),
    ]
    workflow_compliance = sum(1.0 for item in workflow_signals if item) / max(
        1, len(workflow_signals)
    )
    tool_call_count = int(analysis.get("tool_call_count") or 0)
    clarification_count = int(analysis.get("clarification_question_count") or 0)
    user_correction_count = int(analysis.get("user_correction_count") or 0)
    friction = min(1.0, 0.25 * clarification_count + 0.5 * user_correction_count)
    efficiency = max(0.0, 1.0 - 0.05 * max(0, tool_call_count - 2) - friction / 2)
    return {
        "task_completed": bool(analysis.get("task_completed")),
        "workflow_compliance": round(workflow_compliance, 3),
        "user_friction": round(friction, 3),
        "efficiency": round(efficiency, 3),
    }


def parse_judge_response(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Judge output must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Judge output must be a JSON object.")
    relevance = str(payload.get("optimization_relevance", "none"))
    if relevance not in ALLOWED_RELEVANCE:
        raise ValueError("Judge output contains an invalid optimization_relevance.")
    return payload


def merge_interactive_scores(
    *, heuristic_scores: dict[str, Any], judge_scores: dict[str, Any]
) -> dict[str, Any]:
    return {
        "task_success": float(
            judge_scores.get(
                "task_success", 1.0 if heuristic_scores.get("task_completed") else 0.0
            )
        ),
        "user_friction": float(
            judge_scores.get(
                "user_friction", heuristic_scores.get("user_friction", 0.0)
            )
        ),
        "workflow_compliance": float(
            judge_scores.get(
                "workflow_compliance",
                heuristic_scores.get("workflow_compliance", 0.0),
            )
        ),
        "efficiency": float(
            judge_scores.get("efficiency", heuristic_scores.get("efficiency", 0.0))
        ),
        "optimization_relevance": str(
            judge_scores.get("optimization_relevance", "none")
        ),
        "reasoning": str(judge_scores.get("reasoning", "")),
        "heuristics": heuristic_scores,
    }


def build_judge_prompt(trace: dict[str, Any]) -> str:
    return (
        "You are judging a Codex interactive session. "
        "Return only JSON with keys: task_success, user_friction, "
        "workflow_compliance, efficiency, optimization_relevance, reasoning.\n\n"
        f"Thread: {trace.get('thread_name', '')}\n"
        f"Summary:\n{trace.get('analysis_summary', '')}\n"
    )


def run_codex_judge(
    trace: dict[str, Any],
    *,
    codex_bin: str = "codex",
    model: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    command = [codex_bin, "exec", "--json"]
    if model:
        command.extend(["--model", model])
    command.append(build_judge_prompt(trace))
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"codex judge failed (exit={proc.returncode}): {proc.stderr}"
        )
    final_text = ""
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and isinstance(
                item.get("text"), str
            ):
                final_text = item["text"]
    return parse_judge_response(final_text)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score interactive Codex sessions with heuristics and a Codex judge"
    )
    parser.add_argument("--entity", default=DEFAULT_ENTITY)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--trace-file", help="Path to a saved interactive trace JSON")
    parser.add_argument("--judge-model", help="Codex model for the session judge")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not ensure_wandb_api_key():
        print("WANDB_API_KEY is required to score interactive traces.", file=sys.stderr)
        return 2

    weave.init(f"{args.entity}/{args.project}")
    if not args.trace_file:
        print("--trace-file is required.", file=sys.stderr)
        return 2

    trace = json.loads(open(args.trace_file, encoding="utf-8").read())

    @weave.op()
    def score_interactive_trace(trace_payload: dict[str, Any]) -> dict[str, Any]:
        heuristics = score_interactive_heuristics(trace_payload)
        judge = run_codex_judge(
            trace_payload,
            model=args.judge_model,
            timeout_seconds=args.timeout_seconds,
        )
        return merge_interactive_scores(
            heuristic_scores=heuristics,
            judge_scores=judge,
        )

    print(json.dumps(score_interactive_trace(trace), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
