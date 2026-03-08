"""Local evaluation framework — replaces Weave Evaluation, Model, Scorer.

Provides ``LocalEvaluation``, ``LocalModel``, ``LocalScorer``,
``LocalValidJSONScorer``, and ``LocalPydanticScorer`` that produce output
in the exact same schema as Weave's evaluation framework.
"""

from __future__ import annotations

import inspect
import json
from time import perf_counter
from typing import Any

from pydantic import BaseModel


class LocalModel(BaseModel):
    """Base class replacing ``weave.Model``.  Subclasses implement ``predict()``."""

    def predict(self, prompt: str) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError


class LocalScorer:
    """Base class replacing ``weave.Scorer``.

    Supports ``column_map`` for field mapping between case keys and scorer
    parameter names.
    """

    name: str = ""
    column_map: dict[str, str] | None = None

    def score(self, *, output: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ARG002
        raise NotImplementedError


class LocalValidJSONScorer:
    """Replaces ``weave.scorers.ValidJSONScorer``."""

    def score(self, *, output: str) -> dict[str, Any]:
        try:
            json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return {"json_valid": False}
        return {"json_valid": True}


class LocalPydanticScorer:
    """Replaces ``weave.scorers.PydanticScorer``."""

    def __init__(self, model: type[BaseModel]) -> None:
        self._model = model

    def score(self, *, output: str) -> dict[str, Any]:
        try:
            self._model.model_validate_json(output)
        except Exception:
            return {"valid_pydantic": False}
        return {"valid_pydantic": True}


class LocalEvaluation:
    """Replaces ``weave.Evaluation`` — full evaluation runner.

    Produces summary dicts in the exact same schema as Weave so that
    downstream consumers (``rank_variant_results``, ``render_ranked_summary_table``)
    work unchanged.
    """

    def __init__(
        self, name: str, dataset: list[dict[str, Any]], scorers: list[Any]
    ) -> None:
        self.name = name
        self.dataset = dataset
        self.scorers = scorers

    def evaluate(self, model: Any) -> dict[str, Any]:
        """Run evaluation synchronously and return aggregated summary."""
        per_case_results: list[dict[str, Any]] = []

        for case in self.dataset:
            started = perf_counter()
            output = model.predict(case["prompt"])
            latency = perf_counter() - started

            case_result: dict[str, Any] = {"_latency": latency}

            for scorer in self.scorers:
                scorer_name = _scorer_name(scorer)
                kwargs = _build_scorer_kwargs(scorer, case, output)
                result = _call_scorer(scorer, **kwargs)
                case_result[scorer_name] = result

            per_case_results.append(case_result)

        return _aggregate(per_case_results, self.scorers)


def _scorer_name(scorer: Any) -> str:
    """Derive a canonical name for a scorer."""
    if hasattr(scorer, "name") and scorer.name:
        return str(scorer.name)
    if hasattr(scorer, "__name__"):
        return scorer.__name__
    return type(scorer).__name__


def _build_scorer_kwargs(
    scorer: Any, case: dict[str, Any], output: Any
) -> dict[str, Any]:
    """Build keyword arguments for a scorer call using signature introspection."""
    kwargs: dict[str, Any] = {"output": output}

    # Get the score method or callable signature
    if isinstance(scorer, (LocalScorer, LocalValidJSONScorer, LocalPydanticScorer)):
        sig = inspect.signature(scorer.score)
    elif callable(scorer):
        sig = inspect.signature(scorer)
    else:
        return kwargs

    accepted_params = set(sig.parameters.keys()) - {"self", "output"}

    # Apply column_map if present
    column_map = getattr(scorer, "column_map", None) or {}
    mapped_case: dict[str, Any] = {}
    for case_key, param_name in column_map.items():
        if case_key in case:
            mapped_case[param_name] = case[case_key]

    # Add case fields that match accepted params
    for param_name in accepted_params:
        if param_name in mapped_case:
            kwargs[param_name] = mapped_case[param_name]
        elif param_name in case:
            kwargs[param_name] = case[param_name]

    return kwargs


def _call_scorer(scorer: Any, **kwargs: Any) -> dict[str, Any]:
    """Invoke a scorer, handling both class instances and plain functions."""
    if isinstance(scorer, (LocalScorer, LocalValidJSONScorer, LocalPydanticScorer)):
        return scorer.score(**kwargs)
    if callable(scorer):
        return scorer(**kwargs)
    raise TypeError(f"Unsupported scorer type: {type(scorer)}")


def _aggregate(
    per_case_results: list[dict[str, Any]], scorers: list[Any]
) -> dict[str, Any]:
    """Aggregate per-case results into summary matching Weave schema."""
    summary: dict[str, Any] = {}

    # Aggregate model_latency
    latencies = [r["_latency"] for r in per_case_results if "_latency" in r]
    if latencies:
        summary["model_latency"] = {
            "mean": sum(latencies) / len(latencies),
            "count": len(latencies),
        }

    # Aggregate each scorer
    for scorer in scorers:
        name = _scorer_name(scorer)
        scorer_results = [r.get(name, {}) for r in per_case_results if name in r]
        if not scorer_results:
            continue

        # Collect all fields across all results
        all_fields: set[str] = set()
        for result in scorer_results:
            if isinstance(result, dict):
                all_fields.update(result.keys())

        field_summary: dict[str, Any] = {}
        for field in all_fields:
            values = [
                r[field]
                for r in scorer_results
                if isinstance(r, dict) and field in r and r[field] is not None
            ]
            if not values:
                continue

            if all(isinstance(v, bool) for v in values):
                true_count = sum(1 for v in values if v)
                false_count = len(values) - true_count
                field_summary[field] = {
                    "true_count": true_count,
                    "false_count": false_count,
                    "true_fraction": true_count / len(values) if values else 0.0,
                    "count": len(values),
                }
            elif all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in values
            ):
                field_summary[field] = {
                    "mean": sum(values) / len(values),
                    "count": len(values),
                }
            # Skip str, list, None — not aggregated

        summary[name] = field_summary

    return summary
