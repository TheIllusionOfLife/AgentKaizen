from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Iterable

import weave
from weave.trace.settings import UserSettings
from weave.utils.pii_redaction import redact_pii

from codex_scoring import evaluate_output


@dataclass
class ParsedEvents:
    events: list[dict[str, object]]
    final_message: str
    usage: dict
    malformed_lines: int


DEFAULT_PII_REDACTION_FIELDS = [
    "prompt",
    "final_message",
    "stderr",
    "content",
    "content_blocks",
    "messages",
    "tool_calls",
    "arguments",
    "output",
    "analysis_summary",
    "user_task",
    "thread_name",
]


def parse_codex_jsonl(lines: Iterable[str]) -> ParsedEvents:
    events: list[dict[str, object]] = []
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

        if not isinstance(event, dict):
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


def _sanitize_path(path_value: str) -> str:
    if not path_value:
        return path_value
    home_dir = str(pathlib.Path.home())
    if path_value.startswith(home_dir):
        path_value = path_value.replace(home_dir, "~", 1)
    path_value = re.sub(r"^/Users/[^/]+/", "/Users/[REDACTED]/", path_value)
    path_value = re.sub(r"^/home/[^/]+/", "/home/[REDACTED]/", path_value)
    return path_value


def sanitize_command(command: list[str]) -> list[str]:
    return [_sanitize_path(part) for part in command]


def configure_weave_pii_redaction(enabled: bool = True) -> None:
    settings = UserSettings(
        redact_pii=enabled,
        redact_pii_fields=DEFAULT_PII_REDACTION_FIELDS if enabled else [],
    )
    settings.apply()


def apply_builtin_pii_redaction(
    value: dict[str, Any] | str, enabled: bool = True
) -> dict[str, Any] | str:
    if not enabled:
        return value
    try:
        return redact_pii(value)
    except Exception:
        return value


def build_codex_command(
    prompt: str,
    model: str | None = None,
    sandbox: str | None = None,
    profile: str | None = None,
    image_paths: list[str] | None = None,
    codex_args: list[str] | None = None,
) -> list[str]:
    command = ["codex", "exec", "--json"]
    if model:
        command.extend(["--model", model])
    if sandbox:
        command.extend(["--sandbox", sandbox])
    if profile:
        command.extend(["--profile", profile])
    if image_paths:
        for image_path in image_paths:
            command.extend(["--image", image_path])
    if codex_args:
        command.extend(codex_args)
    command.append(prompt)
    return command


def build_prompt_content(
    prompt: str, image_paths: list[str] | None = None
) -> list[dict[str, str]]:
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    for image_path in image_paths or []:
        content.append(
            {"type": "input_image", "image_path": _sanitize_path(image_path)}
        )
    return content


def summarize_modalities(content: list[dict[str, object]]) -> list[str]:
    modalities: list[str] = []
    seen: set[str] = set()
    for block in content:
        block_type = str(block.get("type", ""))
        modality = "image" if "image" in block_type else "text"
        if modality not in seen:
            seen.add(modality)
            modalities.append(modality)
    return modalities


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run codex exec with Weave tracing")
    parser.add_argument(
        "--prompt", required=True, help="Prompt text or '-' to read from stdin"
    )
    parser.add_argument("--model", help="Codex model")
    parser.add_argument("--sandbox", help="Codex sandbox mode")
    parser.add_argument("--profile", help="Codex profile")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Image file to attach to the initial prompt (repeatable)",
    )
    parser.add_argument("--entity", help="W&B entity/team")
    parser.add_argument("--project", help="W&B project")
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
    parser.add_argument(
        "--require-json",
        action="store_true",
        help="Guardrail: output must be valid JSON",
    )
    parser.add_argument(
        "--required-section",
        action="append",
        default=[],
        help="Guardrail: output must include this section text (repeatable)",
    )
    parser.add_argument(
        "--require-file-paths",
        action="store_true",
        help="Guardrail: output must include at least one file path citation",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Timeout for codex exec in seconds",
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


def resolve_weave_project(entity: str | None, project: str | None) -> str:
    resolved_entity = entity or os.environ.get("WANDB_ENTITY")
    resolved_project = project or os.environ.get("WANDB_PROJECT")
    if resolved_entity and resolved_project:
        return f"{resolved_entity}/{resolved_project}"
    raise ValueError(
        "W&B entity and project are required. Pass --entity and --project, or set WANDB_ENTITY and WANDB_PROJECT."
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if not ensure_wandb_api_key():
        print("WANDB_API_KEY is required to send traces to W&B.", file=sys.stderr)
        return 2
    try:
        project_path = resolve_weave_project(args.entity, args.project)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    input_content = build_prompt_content(prompt, image_paths=args.image)
    modalities = summarize_modalities(input_content)

    configure_weave_pii_redaction()
    weave.init(project_path)

    @weave.op()
    def run_codex_exec_traced() -> dict:
        command = build_codex_command(
            prompt=prompt,
            model=args.model,
            sandbox=args.sandbox,
            profile=args.profile,
            image_paths=args.image,
            codex_args=args.codex_arg,
        )
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {
                "command": sanitize_command(command),
                "prompt": prompt,
                "input_content": input_content,
                "modalities": modalities,
                "returncode": 124,
                "stderr": f"codex exec timed out after {args.timeout_seconds} seconds",
                "events": [],
                "malformed_lines": 0,
                "usage": {},
                "final_message": "",
                "guardrails": evaluate_output(
                    output={"text": "", "usage": {}},
                    must_contain=args.must_contain,
                    must_not_contain=args.must_not_contain,
                    exact_match=None,
                    max_chars=args.max_chars,
                    require_json=args.require_json,
                    required_sections=args.required_section,
                    require_file_paths=args.require_file_paths,
                ),
            }
        parsed = parse_codex_jsonl(proc.stdout.splitlines())
        guardrails = evaluate_output(
            output={"text": parsed.final_message, "usage": parsed.usage},
            must_contain=args.must_contain,
            must_not_contain=args.must_not_contain,
            exact_match=None,
            max_chars=args.max_chars,
            require_json=args.require_json,
            required_sections=args.required_section,
            require_file_paths=args.require_file_paths,
        )
        return {
            "command": sanitize_command(command),
            "prompt": prompt,
            "input_content": input_content,
            "modalities": modalities,
            "returncode": proc.returncode,
            "stderr": proc.stderr,
            "events": parsed.events,
            "malformed_lines": parsed.malformed_lines,
            "usage": parsed.usage,
            "final_message": parsed.final_message,
            "guardrails": guardrails,
        }

    result = apply_builtin_pii_redaction(run_codex_exec_traced())
    if result["final_message"]:
        print(result["final_message"])
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr, end="")

    has_guardrails = bool(
        args.must_contain
        or args.must_not_contain
        or args.max_chars is not None
        or args.require_json
        or args.required_section
        or args.require_file_paths
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
