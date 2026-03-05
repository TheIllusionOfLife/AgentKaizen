from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable

import weave

from codex_scoring import evaluate_output

DEFAULT_ENTITY = "mukaiyuya-mukai-entertainment"
DEFAULT_PROJECT = "AgentKaizen"


@dataclass
class ParsedEvents:
    events: list[dict]
    final_message: str
    usage: dict
    malformed_lines: int


def parse_codex_jsonl(lines: Iterable[str]) -> ParsedEvents:
    events: list[dict] = []
    final_message = ""
    usage: dict = {}
    malformed_lines = 0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue

        events.append(event)
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message" and isinstance(
                item.get("text"), str
            ):
                final_message = item["text"]
        if event.get("type") == "turn.completed" and isinstance(
            event.get("usage"), dict
        ):
            usage = event["usage"]

    return ParsedEvents(
        events=events,
        final_message=final_message,
        usage=usage,
        malformed_lines=malformed_lines,
    )


def build_codex_command(
    prompt: str,
    model: str | None = None,
    sandbox: str | None = None,
    profile: str | None = None,
    codex_args: list[str] | None = None,
) -> list[str]:
    command = ["codex", "exec", "--json"]
    if model:
        command.extend(["--model", model])
    if sandbox:
        command.extend(["--sandbox", sandbox])
    if profile:
        command.extend(["--profile", profile])
    if codex_args:
        command.extend(codex_args)
    command.append(prompt)
    return command


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run codex exec with Weave tracing")
    parser.add_argument(
        "--prompt", required=True, help="Prompt text or '-' to read from stdin"
    )
    parser.add_argument("--model", help="Codex model")
    parser.add_argument("--sandbox", help="Codex sandbox mode")
    parser.add_argument("--profile", help="Codex profile")
    parser.add_argument("--entity", default=DEFAULT_ENTITY, help="W&B entity/team")
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="W&B project")
    parser.add_argument(
        "--codex-arg",
        action="append",
        default=[],
        help="Extra argument forwarded to codex exec (repeatable)",
    )
    parser.add_argument(
        "--must-contain",
        action="append",
        default=[],
        help="Guardrail: output must contain this text (repeatable)",
    )
    parser.add_argument(
        "--must-not-contain",
        action="append",
        default=[],
        help="Guardrail: output must not contain this text (repeatable)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        help="Guardrail: maximum output characters",
    )
    parser.add_argument(
        "--guardrail-mode",
        choices=["warn", "fail"],
        default="warn",
        help="On guardrail violations: warn (default) or fail with exit code 3",
    )
    return parser


def load_wandb_api_key_from_env_file(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "WANDB_API_KEY":
            return value.strip().strip("'").strip('"')
    return None


def ensure_wandb_api_key() -> str | None:
    existing = os.environ.get("WANDB_API_KEY")
    if existing:
        return existing

    env_key = load_wandb_api_key_from_env_file(pathlib.Path(".env.local"))
    if env_key:
        os.environ["WANDB_API_KEY"] = env_key
    return env_key


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not ensure_wandb_api_key():
        print("WANDB_API_KEY is required to send traces to W&B.", file=sys.stderr)
        return 2

    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt

    project_path = f"{args.entity}/{args.project}"
    weave.init(project_path)

    @weave.op()
    def run_codex_exec_traced() -> dict:
        command = build_codex_command(
            prompt=prompt,
            model=args.model,
            sandbox=args.sandbox,
            profile=args.profile,
            codex_args=args.codex_arg,
        )
        proc = subprocess.run(command, capture_output=True, text=True)
        parsed = parse_codex_jsonl(proc.stdout.splitlines())
        guardrails = evaluate_output(
            output=parsed.final_message,
            must_contain=args.must_contain,
            must_not_contain=args.must_not_contain,
            max_chars=args.max_chars,
        )
        return {
            "command": command,
            "prompt": prompt,
            "returncode": proc.returncode,
            "stderr": proc.stderr,
            "events": parsed.events,
            "malformed_lines": parsed.malformed_lines,
            "usage": parsed.usage,
            "final_message": parsed.final_message,
            "guardrails": guardrails,
        }

    result = run_codex_exec_traced()
    if result["final_message"]:
        print(result["final_message"])
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr, end="")

    has_guardrails = bool(
        args.must_contain or args.must_not_contain or args.max_chars is not None
    )
    violation = has_guardrails and not result["guardrails"]["pass"]
    if violation:
        print(
            f"Guardrail violations: {json.dumps(result['guardrails'], ensure_ascii=True)}",
            file=sys.stderr,
        )

    exit_code = int(result["returncode"])
    if exit_code == 0 and violation and args.guardrail_mode == "fail":
        return 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
