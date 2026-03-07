"""Backward-compat shim — implementation split across agentkaizen.core and agentkaizen.oneshot."""

from agentkaizen.core import (  # noqa: F401
    DEFAULT_PII_REDACTION_FIELDS,
    SUPPORTED_WANDB_ENV_KEYS,
    ParsedEvents,
    _sanitize_path,
    apply_builtin_pii_redaction,
    build_prompt_content,
    configure_weave_pii_redaction,
    ensure_wandb_api_key,
    parse_codex_jsonl,
    resolve_weave_project,
)
from agentkaizen.oneshot import main  # noqa: F401


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
