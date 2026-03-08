"""LLM-as-a-Judge scorer for offline variant evaluation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agentkaizen._local_eval import LocalScorer
from agentkaizen.runners import get_runner

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> str:
    """Strip markdown fences if present, return raw JSON string."""
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _build_judge_prompt(prompt: str, response: str, rubric: str) -> str:
    return (
        "You are an objective evaluator. Respond with JSON only — no markdown fences.\n\n"
        "<prompt>\n"
        f"{prompt}\n"
        "</prompt>\n\n"
        "<response>\n"
        f"{response}\n"
        "</response>\n\n"
        "<rubric>\n"
        f"{rubric}\n"
        "</rubric>\n\n"
        'Return: {"pass": true|false, "score": 0.0-1.0, "reasoning": "one sentence"}'
    )


class LLMJudgeScorer(LocalScorer):
    """Score an agent response using an LLM as judge."""

    name: str = "llm_judge"

    def __init__(
        self,
        *,
        rubric: str = "",
        runner_name: str = "claude-code",
        model: str | None = None,
    ) -> None:
        self.rubric = rubric
        self.runner_name = runner_name
        self.model = model

    def score(
        self,
        *,
        output: Any,
        prompt: str = "",
        judge_rubric: str = "",
    ) -> dict[str, Any]:
        rubric = judge_rubric or self.rubric
        if not rubric:
            return {"pass": True, "score": None, "reasoning": "no rubric"}

        text = output.get("text", "") if isinstance(output, dict) else str(output)
        judge_prompt = _build_judge_prompt(prompt, text, rubric)
        runner = get_runner(self.runner_name, model=self.model)
        try:
            result = runner.run(judge_prompt, timeout_seconds=60)
            parsed = json.loads(_extract_json(result.final_message))
            if not isinstance(parsed, dict):
                raise ValueError(f"judge returned non-dict: {type(parsed)}")
            score_raw = parsed.get("score")
            try:
                score: float | None = (
                    max(0.0, min(1.0, float(score_raw)))
                    if score_raw is not None
                    else None
                )
            except (TypeError, ValueError):
                score = None
            raw_pass = parsed.get("pass")
            if isinstance(raw_pass, bool):
                passed = raw_pass
            else:
                passed = (score or 0.0) >= 0.5
            return {
                "pass": passed,
                "score": score,
                "reasoning": str(parsed.get("reasoning", "")),
            }
        except Exception as exc:
            logger.warning("LLM judge failed: %s", exc)
            return {"pass": None, "score": None, "reasoning": f"judge error: {exc}"}
