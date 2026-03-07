from __future__ import annotations

import os
import stat
import textwrap
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
        script_path.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                from __future__ import annotations

                import json
                import os
                import sys
                from pathlib import Path


                def emit(message: str, usage: dict[str, int] | None = None) -> int:
                    usage = usage or {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
                    sys.stdout.write(
                        json.dumps(
                            {
                                "type": "item.completed",
                                "item": {"type": "agent_message", "text": message},
                            }
                        )
                        + "\\n"
                    )
                    sys.stdout.write(
                        json.dumps({"type": "turn.completed", "usage": usage}) + "\\n"
                    )
                    return 0


                def read_agents_text(workspace: Path | None) -> str:
                    if workspace is None:
                        workspace = Path(os.environ.get("FAKE_CODEX_DEFAULT_WORKSPACE", os.getcwd()))
                    agents_path = workspace / "AGENTS.md"
                    if not agents_path.exists():
                        return ""
                    return agents_path.read_text(encoding="utf-8")


                def main(argv: list[str]) -> int:
                    if len(argv) < 2 or argv[1] != "exec":
                        print("fake codex only supports 'exec'", file=sys.stderr)
                        return 2

                    args = argv[2:]
                    workspace = None
                    prompt = ""
                    idx = 0
                    while idx < len(args):
                        arg = args[idx]
                        if arg == "-C" and idx + 1 < len(args):
                            workspace = Path(args[idx + 1])
                            idx += 2
                            continue
                        if arg in {"--json", "--skip-git-repo-check"}:
                            idx += 1
                            continue
                        if arg in {"--model", "--sandbox", "--profile", "--image"} and idx + 1 < len(args):
                            idx += 2
                            continue
                        if arg.startswith("--"):
                            idx += 1
                            continue
                        prompt = arg
                        idx += 1
                    agents_text = read_agents_text(workspace).lower()
                    prompt_lower = prompt.lower()

                    if "return only json with keys:" in prompt_lower:
                        return emit(
                            json.dumps(
                                {
                                    "task_success": 0.91,
                                    "user_friction": 0.14,
                                    "workflow_compliance": 0.88,
                                    "efficiency": 0.79,
                                    "optimization_relevance": "agents",
                                    "reasoning": "The session completed with low friction and AGENTS.md is the clearest steering surface.",
                                },
                                ensure_ascii=False,
                            )
                        )
                    if "repair the response and return only valid json" in prompt_lower:
                        return emit(
                            json.dumps(
                                {
                                    "task_success": 0.5,
                                    "user_friction": 0.5,
                                    "workflow_compliance": 0.5,
                                    "efficiency": 0.5,
                                    "optimization_relevance": "none",
                                    "reasoning": "Repaired response.",
                                },
                                ensure_ascii=False,
                            )
                        )
                    if prompt == "Say only: ok":
                        return emit("ok", usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
                    if "respond in english" in prompt_lower:
                        return emit("This repository measures CLI agent behavior with W&B Weave.")
                    if "what does this repository do?" in prompt_lower:
                        if "respond in japanese" in agents_text:
                            return emit("このリポジトリはCLIエージェントの挙動をW&B Weaveで測定します。")
                        return emit("This repository measures CLI agent behavior with W&B Weave.")
                    if "required w&b configuration" in prompt_lower:
                        if "respond in japanese" in agents_text:
                            return emit("必要な設定はWANDB_API_KEY、WANDB_ENTITY、WANDB_PROJECTです。")
                        return emit("Required config: WANDB_API_KEY, WANDB_ENTITY, WANDB_PROJECT.")
                    return emit("fallback response")


                raise SystemExit(main(sys.argv))
                """
            ),
            encoding="utf-8",
        )
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
        current_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{current_path}")
        if default_workspace is not None:
            monkeypatch.setenv("FAKE_CODEX_DEFAULT_WORKSPACE", str(default_workspace))
        return script_path

    return _install
