from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

TEST_WANDB_ENTITY = "test-entity"
TEST_WANDB_PROJECT = "test-project"


def set_wandb_target_env(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    monkeypatch.setenv("WANDB_ENTITY", TEST_WANDB_ENTITY)
    monkeypatch.setenv("WANDB_PROJECT", TEST_WANDB_PROJECT)
    return TEST_WANDB_ENTITY, TEST_WANDB_PROJECT


@pytest.fixture
def install_fake_codex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def _install(*, default_workspace: Path | None = None) -> Path:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        script_path = bin_dir / "codex"
        fixture_source = Path(__file__).with_name("fixtures") / "fake_codex.py"
        script_path.write_text(
            fixture_source.read_text(encoding="utf-8"), encoding="utf-8"
        )
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
        current_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{current_path}")
        monkeypatch.delenv("FAKE_CODEX_DEFAULT_WORKSPACE", raising=False)
        if default_workspace is not None:
            monkeypatch.setenv("FAKE_CODEX_DEFAULT_WORKSPACE", str(default_workspace))
        return script_path

    return _install
