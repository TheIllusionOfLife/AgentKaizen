"""Base protocol and data types for agent runners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class AgentUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AgentResult:
    final_message: str
    usage: AgentUsage
    raw_events: list[dict[str, Any]]
    returncode: int
    stderr: str
    malformed_lines: int = 0


class AgentRunError(RuntimeError):
    """Raised when the agent subprocess fails or times out."""


@runtime_checkable
class AgentRunner(Protocol):
    name: str

    def run(
        self,
        prompt: str,
        *,
        workspace: Path | None = None,
        timeout_seconds: int = 300,
    ) -> AgentResult: ...

    def build_command(
        self, prompt: str, workspace: Path | None = None
    ) -> list[str]: ...
