"""Runner registry: map agent names to runner constructors."""

from __future__ import annotations

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
    return runner_cls(**kwargs)
