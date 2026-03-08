"""Tests for _local_eval — local evaluation framework."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from agentkaizen._local_eval import (
    LocalEvaluation,
    LocalModel,
    LocalPydanticScorer,
    LocalScorer,
    LocalValidJSONScorer,
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


class EchoModel(LocalModel):
    def predict(self, prompt: str) -> dict[str, str]:
        return {
            "text": prompt,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


class FixedModel(LocalModel):
    def __init__(self, response: str):
        self._response = response

    def predict(self, prompt: str) -> dict[str, str]:
        return {
            "text": self._response,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


# --- LocalValidJSONScorer ---


def test_valid_json_scorer_valid():
    scorer = LocalValidJSONScorer()
    result = scorer.score(output='{"key": "value"}')
    assert result["json_valid"] is True


def test_valid_json_scorer_invalid():
    scorer = LocalValidJSONScorer()
    result = scorer.score(output="not json")
    assert result["json_valid"] is False


# --- LocalPydanticScorer ---


class AnswerModel(BaseModel):
    answer: str


def test_pydantic_scorer_valid():
    scorer = LocalPydanticScorer(model=AnswerModel)
    result = scorer.score(output='{"answer": "ok"}')
    assert result["valid_pydantic"] is True


def test_pydantic_scorer_invalid():
    scorer = LocalPydanticScorer(model=AnswerModel)
    result = scorer.score(output='{"wrong": "field"}')
    assert result["valid_pydantic"] is False


# --- LocalScorer column_map ---


class MappedScorer(LocalScorer):
    name = "mapped_test"
    column_map = {"response_schema": "schema_param"}

    def score(self, *, output, schema_param=None):
        return {"has_schema": schema_param is not None}


def test_column_map_maps_case_fields():
    scorer = MappedScorer()
    case = {"prompt": "test", "response_schema": {"type": "object"}}
    model = EchoModel()

    evaluation = LocalEvaluation(name="test", dataset=[case], scorers=[scorer])
    result = evaluation.evaluate(model)
    assert "mapped_test" in result
    pass_info = result["mapped_test"].get("has_schema", {})
    assert pass_info.get("true_count", 0) == 1


# --- Signature-based argument filtering ---


def test_extra_case_keys_dont_cause_type_error():
    """Cases with extra keys like id, suite, task_type shouldn't cause TypeError."""
    cases = [
        {
            "id": "case-1",
            "suite": "test-suite",
            "task_type": "generation",
            "steering_surface": "agents",
            "prompt": "hello world",
            "must_contain": ["hello"],
            "must_not_contain": ["bad"],
            "max_chars": 100,
            "require_json": False,
            "required_sections": [],
            "require_file_paths": False,
        }
    ]
    model = EchoModel()
    scorers = [
        score_contains_all,
        score_forbidden_absent,
        score_max_chars,
        score_json_validity,
        score_required_sections,
        score_token_usage,
    ]

    evaluation = LocalEvaluation(name="test", dataset=cases, scorers=scorers)
    result = evaluation.evaluate(model)

    # Should not raise and should have valid results
    assert "score_contains_all" in result
    assert result["score_contains_all"]["pass"]["true_fraction"] == 1.0


# --- Bool aggregation ---


def test_bool_aggregation():
    cases = [
        {
            "prompt": "hello",
            "must_contain": ["hello"],
            "must_not_contain": [],
            "max_chars": 100,
        },
        {
            "prompt": "world",
            "must_contain": ["missing"],
            "must_not_contain": [],
            "max_chars": 100,
        },
    ]
    model = EchoModel()
    evaluation = LocalEvaluation(
        name="test", dataset=cases, scorers=[score_contains_all]
    )
    result = evaluation.evaluate(model)

    pass_stats = result["score_contains_all"]["pass"]
    assert pass_stats["true_count"] == 1
    assert pass_stats["false_count"] == 1
    assert pass_stats["true_fraction"] == 0.5
    assert pass_stats["count"] == 2


# --- Numeric aggregation ---


def test_numeric_aggregation():
    cases = [
        {
            "prompt": "short",
            "must_contain": [],
            "must_not_contain": [],
            "max_chars": 100,
        },
        {
            "prompt": "longer text",
            "must_contain": [],
            "must_not_contain": [],
            "max_chars": 100,
        },
    ]
    model = EchoModel()
    evaluation = LocalEvaluation(name="test", dataset=cases, scorers=[score_max_chars])
    result = evaluation.evaluate(model)

    length_stats = result["score_max_chars"]["length"]
    assert "mean" in length_stats
    assert length_stats["count"] == 2


# --- Model latency ---


def test_model_latency_aggregated():
    cases = [
        {"prompt": "p1", "must_contain": [], "must_not_contain": [], "max_chars": 100}
    ]
    model = EchoModel()
    evaluation = LocalEvaluation(
        name="test", dataset=cases, scorers=[score_contains_all]
    )
    result = evaluation.evaluate(model)

    assert "model_latency" in result
    assert "mean" in result["model_latency"]
    assert result["model_latency"]["count"] == 1


# --- Full scorer suite ---


def test_all_deterministic_scorers():
    """Run all 10 deterministic scorers + verify no errors."""
    cases = [
        {
            "prompt": '{"answer": "ok"}',
            "must_contain": ["answer"],
            "must_not_contain": ["forbidden"],
            "exact_match": None,
            "max_chars": 500,
            "min_chars": 1,
            "require_json": True,
            "required_sections": [],
            "required_content_groups": [],
            "require_file_paths": False,
        }
    ]
    model = EchoModel()
    scorers = [
        score_contains_all,
        score_forbidden_absent,
        score_exact_match,
        score_max_chars,
        score_min_chars,
        score_json_validity,
        score_required_sections,
        score_required_content_groups,
        score_file_path_citations,
        score_token_usage,
    ]

    evaluation = LocalEvaluation(name="test", dataset=cases, scorers=scorers)
    result = evaluation.evaluate(model)

    assert "score_contains_all" in result
    assert "score_forbidden_absent" in result
    assert "score_exact_match" in result
    assert "score_max_chars" in result
    assert "score_min_chars" in result
    assert "score_json_validity" in result
    assert "score_required_sections" in result
    assert "score_required_content_groups" in result
    assert "score_file_path_citations" in result
    assert "score_token_usage" in result
    assert "model_latency" in result


# --- Golden parity test ---


def test_local_eval_output_consumed_by_rank_and_render():
    """Verify LocalEvaluation output is consumed by rank_variant_results and render."""
    from agentkaizen.evals import rank_variant_results, render_ranked_summary_table

    cases = [
        {
            "prompt": "hello",
            "must_contain": ["hello"],
            "must_not_contain": [],
            "max_chars": 100,
            "require_json": False,
            "required_sections": [],
            "require_file_paths": False,
        }
    ]
    model = EchoModel()
    scorers = [
        score_contains_all,
        score_forbidden_absent,
        score_max_chars,
        score_json_validity,
        score_required_sections,
        score_file_path_citations,
        score_token_usage,
    ]

    evaluation = LocalEvaluation(name="test", dataset=cases, scorers=scorers)
    summary = evaluation.evaluate(model)

    results = [
        {"variant": "baseline", "summary": summary},
        {"variant": "candidate", "summary": summary},
    ]

    ranked = rank_variant_results(
        results,
        quality_similar_threshold=0.02,
        latency_regression_threshold=0.2,
        token_regression_threshold=0.2,
    )
    assert len(ranked) == 2
    assert all("quality_score" in item for item in ranked)

    rendered = render_ranked_summary_table(ranked)
    assert "Ranking Summary:" in rendered
    assert "variant: baseline" in rendered
