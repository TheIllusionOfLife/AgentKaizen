"""Runner registry: map agent names to runner constructors."""

from __future__ import annotations

import dataclasses
from typing import Any

from agentkaizen.runners.base import AgentRunner
from agentkaizen.runners.claude_code import ClaudeCodeRunner
from agentkaizen.runners.codex import CodexRunner

RUNNERS: dict[str, type] = {
    "codex": CodexRunner,
    "claude-code": ClaudeCodeRunner,
}


def get_runner(name: str = "codex", **kwargs: Any) -> AgentRunner:
    """Return an instantiated runner for the given agent name."""
    runner_cls = RUNNERS.get(name)
    if runner_cls is None:
        supported = ", ".join(sorted(RUNNERS))
        raise ValueError(f"Unknown agent runner {name!r}. Supported: {supported}")
    accepted = {f.name for f in dataclasses.fields(runner_cls) if f.init}
    filtered = {k: v for k, v in kwargs.items() if k in accepted}
    unsupported = set(kwargs) - accepted
    if unsupported:
        import warnings

        warnings.warn(
            f"Runner {name!r} ignoring unsupported kwargs: {sorted(unsupported)}",
            stacklevel=2,
        )
    return runner_cls(**filtered)
