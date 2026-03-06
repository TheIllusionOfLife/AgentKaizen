"""Tests for agentkaizen.config: loading, defaults, CLI override precedence."""

from __future__ import annotations

import textwrap
from argparse import Namespace

from agentkaizen.config import AgentKaizenConfig, load_config, merge_cli_args


# ---------------------------------------------------------------------------
# AgentKaizenConfig defaults
# ---------------------------------------------------------------------------


def test_default_config_values():
    cfg = AgentKaizenConfig()
    assert cfg.agent == "codex"
    assert cfg.cases == "evals/cases"
    assert cfg.entity is None
    assert cfg.project is None
    assert cfg.model is None
    assert cfg.timeout_seconds == 300
    assert cfg.scoring_backend == "subagent"


# ---------------------------------------------------------------------------
# load_config — missing file / missing section
# ---------------------------------------------------------------------------


def test_load_config_returns_defaults_when_no_pyproject(tmp_path):
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert cfg == AgentKaizenConfig()


def test_load_config_returns_defaults_when_section_absent(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[project]\nname = 'foo'\n", encoding="utf-8")
    cfg = load_config(toml)
    assert cfg == AgentKaizenConfig()


# ---------------------------------------------------------------------------
# load_config — reads [tool.agentkaizen]
# ---------------------------------------------------------------------------


def test_load_config_reads_agent_and_project(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        textwrap.dedent("""\
            [tool.agentkaizen]
            agent = "claude-code"
            project = "my-project"
            entity = "my-team"
        """),
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert cfg.agent == "claude-code"
    assert cfg.project == "my-project"
    assert cfg.entity == "my-team"


def test_load_config_reads_numeric_and_string_fields(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        textwrap.dedent("""\
            [tool.agentkaizen]
            timeout_seconds = 600
            scoring_backend = "external"
            cases = "evals/suite"
        """),
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert cfg.timeout_seconds == 600
    assert cfg.scoring_backend == "external"
    assert cfg.cases == "evals/suite"


def test_load_config_unknown_keys_are_ignored(tmp_path):
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        textwrap.dedent("""\
            [tool.agentkaizen]
            agent = "codex"
            unknown_future_key = "value"
        """),
        encoding="utf-8",
    )
    # Should not raise
    cfg = load_config(toml)
    assert cfg.agent == "codex"


# ---------------------------------------------------------------------------
# merge_cli_args — CLI overrides config
# ---------------------------------------------------------------------------


def test_merge_cli_args_cli_overrides_config_values():
    cfg = AgentKaizenConfig(agent="codex", model=None, timeout_seconds=300)
    args = Namespace(agent="claude-code", model="claude-opus-4-6", timeout_seconds=600)
    merged = merge_cli_args(cfg, args)
    assert merged.agent == "claude-code"
    assert merged.model == "claude-opus-4-6"
    assert merged.timeout_seconds == 600


def test_merge_cli_args_none_does_not_override_config():
    cfg = AgentKaizenConfig(agent="codex", model="gpt-4", timeout_seconds=300)
    # CLI args with None values should not override config
    args = Namespace(agent=None, model=None, timeout_seconds=None)
    merged = merge_cli_args(cfg, args)
    assert merged.agent == "codex"
    assert merged.model == "gpt-4"
    assert merged.timeout_seconds == 300


def test_merge_cli_args_partial_override():
    cfg = AgentKaizenConfig(agent="codex", model="old-model", entity="my-team")
    args = Namespace(agent=None, model="new-model", entity=None)
    merged = merge_cli_args(cfg, args)
    assert merged.agent == "codex"  # not overridden
    assert merged.model == "new-model"  # overridden
    assert merged.entity == "my-team"  # not overridden


def test_merge_cli_args_returns_new_instance():
    cfg = AgentKaizenConfig(agent="codex")
    args = Namespace(agent="claude-code")
    merged = merge_cli_args(cfg, args)
    assert merged is not cfg
    assert cfg.agent == "codex"  # original unchanged


def test_merge_cli_args_ignores_unknown_cli_attrs():
    """Extra attributes in Namespace that aren't config fields are silently ignored."""
    cfg = AgentKaizenConfig()
    args = Namespace(unknown_field="value", agent=None)
    merged = merge_cli_args(cfg, args)
    assert merged == cfg
