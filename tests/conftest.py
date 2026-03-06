import pytest

TEST_WANDB_ENTITY = "test-entity"
TEST_WANDB_PROJECT = "test-project"


def set_wandb_target_env(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    monkeypatch.setenv("WANDB_ENTITY", TEST_WANDB_ENTITY)
    monkeypatch.setenv("WANDB_PROJECT", TEST_WANDB_PROJECT)
    return TEST_WANDB_ENTITY, TEST_WANDB_PROJECT
