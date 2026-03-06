"""AgentKaizen configuration: load from pyproject.toml, merge with CLI args."""

from __future__ import annotations

import dataclasses
from argparse import Namespace
from pathlib import Path
from typing import Any


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
    """Read [tool.agentkaizen] from pyproject.toml; fall back to defaults."""
    resolved = _resolve_path(path)
    if resolved is None or not resolved.exists():
        return AgentKaizenConfig()

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return AgentKaizenConfig()

    section: dict[str, Any] = data.get("tool", {}).get("agentkaizen", {})
    if not section:
        return AgentKaizenConfig()

    fields = {f.name for f in dataclasses.fields(AgentKaizenConfig)}
    kwargs = {k: v for k, v in section.items() if k in fields}
    return AgentKaizenConfig(**kwargs)


def merge_cli_args(config: AgentKaizenConfig, args: Namespace) -> AgentKaizenConfig:
    """Return a new config with non-None CLI args overriding config values."""
    fields = {f.name for f in dataclasses.fields(AgentKaizenConfig)}
    overrides: dict[str, Any] = {}
    for name in fields:
        cli_value = getattr(args, name, None)
        if cli_value is not None:
            overrides[name] = cli_value
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
