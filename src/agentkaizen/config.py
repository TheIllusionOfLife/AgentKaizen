"""AgentKaizen configuration: load from pyproject.toml, merge with CLI args."""

from __future__ import annotations

import dataclasses
import os
from argparse import Namespace
from pathlib import Path
from typing import Any

_ENV_PREFIX = "AGENTKAIZEN_"
_INT_FIELDS = {"timeout_seconds"}

# Maps WANDB_* env vars to config field names as secondary fallback.
_WANDB_ENV_MAP: dict[str, str] = {
    "WANDB_ENTITY": "entity",
    "WANDB_PROJECT": "project",
}


@dataclasses.dataclass
class AgentKaizenConfig:
    agent: str = "codex"
    cases: str = "evals/cases"
    entity: str | None = None
    project: str | None = None
    model: str | None = None
    timeout_seconds: int = 300
    scoring_backend: str = "subagent"


def load_config(path: Path | None = None) -> AgentKaizenConfig:
    """Read [tool.agentkaizen] from pyproject.toml, then env vars, then defaults."""
    section = _load_pyproject_section(path)

    # Layer 2: env vars fill gaps
    fields = {f.name for f in dataclasses.fields(AgentKaizenConfig)}
    for name in fields:
        if name not in section:
            env_val = os.environ.get(f"{_ENV_PREFIX}{name.upper()}")
            if env_val is not None:
                if name in _INT_FIELDS:
                    try:
                        section[name] = int(env_val)
                    except ValueError:
                        import warnings

                        warnings.warn(
                            f"Ignoring non-integer value for {_ENV_PREFIX}{name.upper()}: {env_val!r}",
                            stacklevel=2,
                        )
                else:
                    section[name] = env_val

    # Layer 2b: WANDB_* env vars as fallback for entity/project
    for wandb_key, field_name in _WANDB_ENV_MAP.items():
        if field_name not in section:
            wandb_val = os.environ.get(wandb_key)
            if wandb_val:
                section[field_name] = wandb_val

    # Layer 3: dataclass defaults for anything still missing
    kwargs = {k: v for k, v in section.items() if k in fields}
    return AgentKaizenConfig(**kwargs)


def _load_pyproject_section(path: Path | None = None) -> dict[str, Any]:
    """Extract [tool.agentkaizen] dict from pyproject.toml, or empty dict."""
    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return {}

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}

    section: dict[str, Any] = data.get("tool", {}).get("agentkaizen", {})
    return dict(section)


def merge_cli_args(
    config: AgentKaizenConfig,
    args: Namespace,
    *,
    aliases: dict[str, str] | None = None,
) -> AgentKaizenConfig:
    """Return a new config with non-None CLI args overriding config values.

    ``aliases`` maps CLI arg names to config field names, e.g.
    ``{"judge_model": "model"}`` so that ``--judge-model`` overrides ``config.model``.
    """
    alias_map = aliases or {}
    fields = {f.name for f in dataclasses.fields(AgentKaizenConfig)}
    overrides: dict[str, Any] = {}
    for name in fields:
        cli_value = getattr(args, name, None)
        if cli_value is not None:
            overrides[name] = cli_value
    # Apply aliased CLI args
    for cli_name, config_name in alias_map.items():
        if config_name in fields:
            cli_value = getattr(args, cli_name, None)
            if cli_value is not None:
                overrides[config_name] = cli_value
    return dataclasses.replace(config, **overrides)


def _resolve_path(path: Path | None) -> Path | None:
    if path is not None:
        return path
    # Search upward from cwd for pyproject.toml
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            return candidate
    return None
