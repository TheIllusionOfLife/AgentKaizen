"""One-shot Codex CLI runner with Weave tracing."""

from __future__ import annotations

import argparse
import json
import subprocess  # noqa: F401  (re-exported for test patchability)
import sys

import weave

from agentkaizen.runners import get_runner
from agentkaizen.runners.base import AgentRunError
from agentkaizen.core import (
    DEFAULT_PII_REDACTION_FIELDS,  # noqa: F401  (re-exported for test access)
    SUPPORTED_WANDB_ENV_KEYS,  # noqa: F401  (re-exported for test access)
    ParsedEvents,  # noqa: F401  (re-exported for test access)
    _sanitize_path,  # noqa: F401  (re-exported for test access)
    apply_builtin_pii_redaction,
    build_prompt_content,
    configure_weave_pii_redaction,
    ensure_wandb_api_key,
    ensure_wandb_env,  # noqa: F401  (re-exported for test access)
    infer_wandb_entity,  # noqa: F401  (re-exported for test patchability)
    load_wandb_api_key_from_env_file,  # noqa: F401  (re-exported for test access)
    load_wandb_env_from_env_file,  # noqa: F401  (re-exported for test access)
    parse_codex_jsonl,  # noqa: F401  (re-exported for test access)
    resolve_weave_project,  # noqa: F401  (re-exported for test patchability)
    sanitize_command,
    summarize_modalities,
)
from agentkaizen.scoring import evaluate_output


def build_codex_command(
    prompt: str,
    model: str | None = None,
    sandbox: str | None = None,
    profile: str | None = None,
    image_paths: list[str] | None = None,
    codex_args: list[str] | None = None,
) -> list[str]:
    """Backward-compat wrapper; delegates to CodexRunner.build_command()."""
    from agentkaizen.runners.codex import CodexRunner

    runner = CodexRunner(
        model=model,
        sandbox=sandbox,
        profile=profile,
        image_paths=image_paths or [],
        extra_args=codex_args or [],
    )
    return runner.build_command(prompt)


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

    runner = get_runner(
        "codex",
        model=args.model,
        sandbox=args.sandbox,
        profile=args.profile,
        image_paths=args.image,
        extra_args=args.codex_arg,
    )

    @weave.op(name="run_codex_exec_traced")  # freeze op name across refactor
    def run_codex_exec_traced() -> dict:
        command = runner.build_command(prompt)
        try:
            result = runner.run(prompt, timeout_seconds=args.timeout_seconds)
        except AgentRunError as exc:
            return {
                "command": sanitize_command(command),
                "prompt": prompt,
                "input_content": input_content,
                "modalities": modalities,
                "returncode": 124,
                "stderr": str(exc),
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
        guardrails = evaluate_output(
            output={"text": result.final_message, "usage": vars(result.usage)},
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
            "returncode": result.returncode,
            "stderr": result.stderr,
            "events": result.raw_events,
            "malformed_lines": result.malformed_lines,
            "usage": vars(result.usage),
            "final_message": result.final_message,
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
