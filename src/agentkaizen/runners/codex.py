"""Codex CLI agent runner."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from agentkaizen.core import parse_codex_jsonl
from agentkaizen.runners.base import AgentResult, AgentRunError, AgentUsage


@dataclass
class CodexRunner:
    name: str = "codex"
    model: str | None = None
    sandbox: str | None = None
    profile: str | None = None
    image_paths: list[str] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)
    skip_git_repo_check: bool = False

    def build_command(self, prompt: str, workspace: Path | None = None) -> list[str]:
        command = ["codex", "exec"]
        if workspace:
            command.extend(["-C", str(workspace)])
        command.append("--json")
        if self.model:
            command.extend(["--model", self.model])
        if self.sandbox:
            command.extend(["--sandbox", self.sandbox])
        if self.profile:
            command.extend(["--profile", self.profile])
        for image_path in self.image_paths:
            command.extend(["--image", image_path])
        command.extend(self.extra_args)
        if self.skip_git_repo_check and "--skip-git-repo-check" not in command:
            command.append("--skip-git-repo-check")
        command.append(prompt)
        return command

    def run(
        self,
        prompt: str,
        *,
        workspace: Path | None = None,
        timeout_seconds: int = 300,
    ) -> AgentResult:
        command = self.build_command(prompt, workspace=workspace)
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentRunError(
                f"codex exec timed out after {timeout_seconds} seconds"
            ) from exc
        parsed = parse_codex_jsonl(proc.stdout.splitlines())
        input_tokens = int(parsed.usage.get("input_tokens") or 0)
        output_tokens = int(parsed.usage.get("output_tokens") or 0)
        total_tokens = int(
            parsed.usage.get("total_tokens") or (input_tokens + output_tokens)
        )
        usage = AgentUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        return AgentResult(
            final_message=parsed.final_message,
            usage=usage,
            raw_events=parsed.events,
            returncode=proc.returncode,
            stderr=proc.stderr,
            malformed_lines=parsed.malformed_lines,
        )
