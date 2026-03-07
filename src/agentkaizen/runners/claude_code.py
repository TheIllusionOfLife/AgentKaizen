"""Claude Code CLI agent runner."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agentkaizen.runners.base import AgentResult, AgentRunError, AgentUsage


@dataclass
class ClaudeCodeRunner:
    name: str = "claude-code"
    model: str | None = None
    extra_args: list[str] = field(default_factory=list)

    def build_command(self, prompt: str, workspace: Path | None = None) -> list[str]:
        command = ["claude", "-p", prompt, "--output-format", "json"]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(self.extra_args)
        return command

    def run(
        self,
        prompt: str,
        *,
        workspace: Path | None = None,
        timeout_seconds: int = 300,
    ) -> AgentResult:
        command = self.build_command(prompt, workspace=workspace)
        cwd = str(workspace) if workspace else None
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentRunError(
                f"claude exec timed out after {timeout_seconds} seconds"
            ) from exc

        if proc.returncode != 0:
            raise AgentRunError(
                f"claude exited with code {proc.returncode}: {proc.stderr[:200]!r}"
            )

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AgentRunError(
                f"claude output was not valid JSON: {proc.stdout[:200]!r}"
            ) from exc

        if not isinstance(payload, dict):
            raise AgentRunError(
                f"claude output was not a JSON object: {proc.stdout[:200]!r}"
            )

        if payload.get("is_error"):
            raise AgentRunError(
                f"claude returned an error: {payload.get('result', '')}"
            )

        final_message = str(payload.get("result", ""))
        return AgentResult(
            final_message=final_message,
            usage=AgentUsage(),
            raw_events=[payload],
            returncode=proc.returncode,
            stderr=proc.stderr,
        )
