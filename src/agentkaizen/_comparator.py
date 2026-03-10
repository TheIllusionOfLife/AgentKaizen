"""Blind A/B Comparator — side-by-side variant comparison with diagnostic reasoning."""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

from agentkaizen.runners import get_runner

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

DEFAULT_RUBRIC_DIMENSIONS = [
    "instruction_adherence",
    "completeness",
    "efficiency",
    "correctness",
]


def _extract_json(text: str) -> str:
    """Strip markdown fences if present, return raw JSON string."""
    match = _JSON_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _sanitize_for_prompt(text: str) -> str:
    """Prevent XML tag injection in comparator prompt by escaping closing tags."""
    for tag in ("</response_a>", "</response_b>", "</task_prompt>", "</custom_rubric>"):
        text = text.replace(tag, tag.replace("</", "< /"))
    return text


@dataclass
class ComparatorResult:
    """Result of a blind A/B comparison."""

    winner: str  # "A" | "B" | "tie"
    rubric_scores: dict[str, dict[str, int]]  # dim -> {"A": score, "B": score}
    reasoning: str
    winner_strengths: list[str]
    loser_weaknesses: list[str]


def _build_comparator_prompt(
    output_a: str, output_b: str, prompt: str, rubric: str
) -> str:
    """Build the judge prompt for blind A/B comparison with sanitized inputs."""
    output_a = _sanitize_for_prompt(output_a)
    output_b = _sanitize_for_prompt(output_b)
    dimensions = "\n".join(
        f"- {dim}: Rate 1-5 for each response" for dim in DEFAULT_RUBRIC_DIMENSIONS
    )
    rubric_section = (
        f"\n<custom_rubric>\n{rubric}\n</custom_rubric>\n" if rubric else ""
    )

    return (
        "You are a blind evaluator comparing two AI agent responses. "
        "You do not know which is baseline or candidate. "
        "Evaluate both responses objectively.\n\n"
        "<task_prompt>\n"
        f"{prompt}\n"
        "</task_prompt>\n\n"
        "<response_a>\n"
        f"{output_a}\n"
        "</response_a>\n\n"
        "<response_b>\n"
        f"{output_b}\n"
        "</response_b>\n\n"
        f"Evaluation dimensions:\n{dimensions}\n"
        f"{rubric_section}\n"
        "Return JSON only (no markdown fences):\n"
        "{\n"
        '  "winner": "A" | "B" | "tie",\n'
        '  "rubric_scores": {"dimension": {"A": 1-5, "B": 1-5}, ...},\n'
        '  "reasoning": "one paragraph",\n'
        '  "winner_strengths": ["..."],\n'
        '  "loser_weaknesses": ["..."]\n'
        "}"
    )


class ComparatorScorer:
    """Blind A/B comparator that evaluates two outputs without knowing which is baseline."""

    def __init__(
        self,
        rubric: str = "",
        runner_name: str = "claude-code",
        model: str | None = None,
        timeout_seconds: int = 120,
    ) -> None:
        self.rubric = rubric
        self.runner_name = runner_name
        self.model = model
        self.timeout_seconds = timeout_seconds

    def compare(self, output_a: str, output_b: str, prompt: str) -> ComparatorResult:
        """Compare two outputs blindly, returning winner and analysis."""
        # Randomly shuffle to eliminate position bias
        swapped = random.random() < 0.5
        if swapped:
            presented_a, presented_b = output_b, output_a
        else:
            presented_a, presented_b = output_a, output_b

        comparator_prompt = _build_comparator_prompt(
            presented_a, presented_b, prompt, self.rubric
        )

        runner = get_runner(self.runner_name, model=self.model)
        try:
            result = runner.run(comparator_prompt, timeout_seconds=self.timeout_seconds)
            raw_json = _extract_json(result.final_message)
            parsed = json.loads(raw_json)
            if not isinstance(parsed, dict):
                raise ValueError(f"Comparator returned non-dict: {type(parsed)}")
        except Exception as exc:
            logger.warning("Comparator failed: %s", exc)
            return ComparatorResult(
                winner="tie",
                rubric_scores={},
                reasoning=f"Comparator error: {exc}",
                winner_strengths=[],
                loser_weaknesses=[],
            )

        raw_winner = str(parsed.get("winner", "tie")).upper()

        # De-shuffle: map response winner back to original positions
        if raw_winner in ("A", "B"):
            if swapped:
                winner = "B" if raw_winner == "A" else "A"
            else:
                winner = raw_winner
        else:
            winner = "tie"

        # De-shuffle rubric scores
        rubric_scores = parsed.get("rubric_scores", {})
        if swapped and isinstance(rubric_scores, dict):
            deshuffled_scores: dict[str, dict[str, int]] = {}
            for dim, scores in rubric_scores.items():
                if isinstance(scores, dict):
                    deshuffled_scores[dim] = {
                        "A": scores.get("B", 0),
                        "B": scores.get("A", 0),
                    }
                else:
                    deshuffled_scores[dim] = scores
            rubric_scores = deshuffled_scores

        return ComparatorResult(
            winner=winner,
            rubric_scores=rubric_scores,
            reasoning=str(parsed.get("reasoning", "")),
            winner_strengths=list(parsed.get("winner_strengths", [])),
            loser_weaknesses=list(parsed.get("loser_weaknesses", [])),
        )
