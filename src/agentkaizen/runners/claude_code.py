"""Claude Code CLI agent runner."""

from __future__ import annotations

import json
import os
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
        # Strip CLAUDECODE and all CLAUDE_CODE_* vars so nested claude -p calls
        # behave as a clean invocation from within an active Claude Code session.
        # CLAUDECODE alone is insufficient: CLAUDE_CODE_ENTRYPOINT causes stream-json
        # output format, and CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS leaks the outer
        # session's tool list into the nested call.
        env = {
            k: v
            for k, v in os.environ.items()
            if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")
        }  # noqa: S603
        try:
            proc = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentRunError(
                f"claude exec timed out after {timeout_seconds} seconds"
            ) from exc
        except OSError as exc:
            raise AgentRunError(
                f"claude exec failed to start ({exc}): {command[0]!r}"
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

        # When CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is set (e.g. via ~/.claude/settings.json),
        # --output-format json returns a JSON array of stream events instead of a single
        # result object. Extract the result event from the array in that case.
        if isinstance(payload, list):
            result_event = next(
                (ev for ev in payload if isinstance(ev, dict) and ev.get("type") == "result"),
                None,
            )
            if result_event is None:
                raise AgentRunError(
                    f"claude stream output contained no result event: {proc.stdout[:200]!r}"
                )
            payload = result_event

        if not isinstance(payload, dict):
            raise AgentRunError(
                f"claude output was not a JSON object: {proc.stdout[:200]!r}"
            )

        if payload.get("is_error"):
            error_detail = (
                payload.get("error")
                or payload.get("message")
                or payload.get("result")
                or ""
            )
            raise AgentRunError(f"claude returned an error: {error_detail}")

        if payload.get("type") != "result" or not isinstance(
            payload.get("result"), str
        ):
            raise AgentRunError(
                f"claude returned unexpected payload shape: {proc.stdout[:200]!r}"
            )

        raw_usage = payload.get("usage") or {}
        usage = AgentUsage(
            input_tokens=int(raw_usage.get("input_tokens") or 0),
            output_tokens=int(raw_usage.get("output_tokens") or 0),
            total_tokens=int(raw_usage.get("total_tokens") or 0),
        )

        return AgentResult(
            final_message=payload["result"],
            usage=usage,
            raw_events=[payload],
            returncode=proc.returncode,
            stderr=proc.stderr,
        )
