"""Tests for LLMJudgeScorer and helpers in _llm_judge."""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agentkaizen._llm_judge import LLMJudgeScorer, _build_judge_prompt, _extract_json
from agentkaizen.runners.base import AgentResult, AgentUsage


def _make_result(text: str) -> AgentResult:
    return AgentResult(
        final_message=text,
        usage=AgentUsage(),
        raw_events=[],
        returncode=0,
        stderr="",
    )


class FakeRunner:
    name = "fake"

    def __init__(self, response: str):
        self._response = response

    def run(self, prompt: str, *, workspace=None, timeout_seconds: int = 300):
        return _make_result(self._response)


def test_llm_judge_parses_valid_json_response(monkeypatch):
    scorer = LLMJudgeScorer(rubric="Is it correct?", runner_name="fake")
    import agentkaizen._llm_judge as judge_mod

    monkeypatch.setattr(
        judge_mod,
        "get_runner",
        lambda name, **kw: FakeRunner(
            '{"pass": true, "score": 0.9, "reasoning": "looks good"}'
        ),
    )

    result = scorer.score(output={"text": "hello world"}, prompt="say hello")

    assert result["pass"] is True
    assert result["score"] == pytest.approx(0.9)
    assert result["reasoning"] == "looks good"


def test_llm_judge_runner_exception_returns_none_values(monkeypatch):
    scorer = LLMJudgeScorer(rubric="Is it correct?", runner_name="fake")
    import agentkaizen._llm_judge as judge_mod

    def _raise(*args, **kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(
        judge_mod, "get_runner", lambda name, **kw: type("R", (), {"run": _raise})()
    )

    result = scorer.score(output={"text": "hello"}, prompt="say hello")

    assert result["pass"] is None
    assert result["score"] is None
    assert "judge error" in result["reasoning"]


def test_llm_judge_no_rubric_returns_pass_true():
    scorer = LLMJudgeScorer(rubric="", runner_name="fake")

    result = scorer.score(output={"text": "hello"}, prompt="say hello")

    assert result["pass"] is True
    assert result["score"] is None
    assert result["reasoning"] == "no rubric"


def test_build_judge_prompt_includes_all_parts():
    prompt_text = "Tell me about Python"
    response_text = "Python is a language"
    rubric_text = "Is it accurate?"

    judge_prompt = _build_judge_prompt(prompt_text, response_text, rubric_text)

    assert prompt_text in judge_prompt
    assert response_text in judge_prompt
    assert rubric_text in judge_prompt
    assert "pass" in judge_prompt
    assert "score" in judge_prompt
    assert "reasoning" in judge_prompt


def test_llm_judge_clamps_score_out_of_range(monkeypatch):
    scorer = LLMJudgeScorer(rubric="check", runner_name="fake")
    import agentkaizen._llm_judge as judge_mod

    monkeypatch.setattr(
        judge_mod,
        "get_runner",
        lambda name, **kw: FakeRunner(
            '{"pass": "false", "score": 1.5, "reasoning": "over"}'
        ),
    )

    result = scorer.score(output={"text": "x"}, prompt="q")

    # "false" string is falsy but not a bool; score >= 0.5 so pass=True
    assert result["pass"] is True
    assert result["score"] == pytest.approx(1.0)  # clamped


def test_extract_json_strips_markdown_fences():
    raw = '```json\n{"pass": true}\n```'
    assert _extract_json(raw) == '{"pass": true}'


def test_extract_json_returns_plain_text_unchanged():
    raw = '{"pass": false}'
    assert _extract_json(raw) == '{"pass": false}'


def test_llm_judge_per_case_rubric_overrides_global(monkeypatch):
    """per-case judge_rubric kwarg must take precedence over the global rubric."""
    used_prompts: list[str] = []

    class CapturingRunner:
        def run(self, prompt: str, *, workspace=None, timeout_seconds: int = 300):
            used_prompts.append(prompt)
            return _make_result('{"pass": true, "score": 1.0, "reasoning": "ok"}')

    import agentkaizen._llm_judge as judge_mod

    monkeypatch.setattr(judge_mod, "get_runner", lambda name, **kw: CapturingRunner())

    scorer = LLMJudgeScorer(rubric="global rubric", runner_name="fake")
    scorer.score(
        output={"text": "answer"},
        prompt="question",
        judge_rubric="per-case rubric",
    )

    assert used_prompts, "runner was not called"
    assert "per-case rubric" in used_prompts[0]
    assert "global rubric" not in used_prompts[0]
