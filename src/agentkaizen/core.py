"""Shared infrastructure: W&B env resolution, PII redaction, JSONL parser."""

from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from dotenv import dotenv_values
from weave.trace.settings import UserSettings
from weave.utils.pii_redaction import redact_pii


@dataclass
class ParsedEvents:
    events: list[dict[str, object]]
    final_message: str
    usage: dict
    malformed_lines: int


DEFAULT_PII_REDACTION_FIELDS = [
    "prompt",
    "input_content",
    "final_message",
    "stderr",
    "command",
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

SUPPORTED_WANDB_ENV_KEYS = [
    "WANDB_API_KEY",
    "WANDB_ENTITY",
    "WANDB_PROJECT",
    "WANDB_BASE_URL",
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


def load_wandb_env_from_env_file(path: pathlib.Path) -> dict[str, str]:
    if not path.exists():
        return {}

    loaded = dotenv_values(path)
    return {
        key: value
        for key, value in loaded.items()
        if key in SUPPORTED_WANDB_ENV_KEYS and value is not None
    }


def load_wandb_api_key_from_env_file(path: pathlib.Path) -> str | None:
    return load_wandb_env_from_env_file(path).get("WANDB_API_KEY")


def ensure_wandb_env() -> dict[str, str]:
    env_file_values = load_wandb_env_from_env_file(pathlib.Path(".env.local"))
    resolved: dict[str, str] = {}
    for key in SUPPORTED_WANDB_ENV_KEYS:
        existing = os.environ.get(key)
        if existing:
            resolved[key] = existing
            continue
        env_value = env_file_values.get(key)
        if env_value:
            os.environ[key] = env_value
            resolved[key] = env_value
    return resolved


def infer_wandb_entity() -> str | None:
    try:
        import wandb
    except ImportError:
        return None

    try:
        viewer = wandb.Api().viewer
    except Exception:
        return None

    entity = getattr(viewer, "entity", None) or getattr(viewer, "username", None)
    if not entity:
        return None
    return str(entity)


def ensure_wandb_api_key() -> str | None:
    return ensure_wandb_env().get("WANDB_API_KEY")


def resolve_weave_project(entity: str | None, project: str | None) -> str:
    ensure_wandb_env()
    resolved_entity = entity or os.environ.get("WANDB_ENTITY") or infer_wandb_entity()
    resolved_project = project or os.environ.get("WANDB_PROJECT")
    if resolved_entity and not os.environ.get("WANDB_ENTITY"):
        os.environ["WANDB_ENTITY"] = resolved_entity
    if resolved_entity and resolved_project:
        return f"{resolved_entity}/{resolved_project}"
    raise ValueError(
        "W&B project resolution requires WANDB_PROJECT and an entity. Pass --entity/--project, set WANDB_ENTITY/WANDB_PROJECT, or put them in .env.local. WANDB_ENTITY can be inferred from your logged-in W&B account, but WANDB_PROJECT must be set explicitly."
    )
