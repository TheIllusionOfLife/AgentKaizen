#!/usr/bin/env python3
"""Setup checker for AgentKaizen skill. Stdlib only. Exit 0 = all required checks pass."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _check_uv() -> bool:
    print("[CHECK] uv package manager")
    path = shutil.which("uv")
    if path:
        print(f"  [OK] uv found: {path}")
        return True
    print("  [FAIL] uv not found.")
    print("  Fix: curl -LsSf https://astral.sh/uv/install.sh | sh")
    return False


def _check_agentkaizen_cli() -> bool:
    print("[CHECK] agentkaizen CLI")
    if not Path("pyproject.toml").exists():
        print(
            "  [INFO] Run this from the AgentKaizen repo root"
            " (pyproject.toml not found in current directory)"
        )
    try:
        result = subprocess.run(
            ["uv", "run", "agentkaizen", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print("  [OK] agentkaizen CLI available")
            return True
        print(f"  [FAIL] agentkaizen --help exited {result.returncode}")
        if result.stderr.strip():
            print(f"         {result.stderr.strip()}")
    except FileNotFoundError:
        print("  [FAIL] uv not found — cannot run agentkaizen")
    except subprocess.TimeoutExpired:
        print("  [FAIL] agentkaizen --version timed out after 30s")
    print("  Fix: git clone https://github.com/TheIllusionOfLife/AgentKaizen")
    print("       cd AgentKaizen && uv sync --group dev")
    return False


def _check_agent_clis() -> None:
    print("[CHECK] agent CLIs (optional)")
    found = [cli for cli in ("codex", "claude") if shutil.which(cli)]
    if found:
        print(f"  [OK] found: {', '.join(found)}")
    else:
        print("  [WARN] neither codex nor claude found — one-shot runs will fail")
        print("         Install Codex: npm install -g @openai/codex")
        print("         Install Claude Code: npm install -g @anthropic-ai/claude-code")


def _check_wandb() -> None:
    print("[CHECK] W&B configuration (optional)")
    api_key = os.environ.get("WANDB_API_KEY")
    if not api_key:
        env_local = Path(".env.local")
        if env_local.exists() and "WANDB_API_KEY" in env_local.read_text():
            api_key = "(found in .env.local)"
    if api_key:
        print("  [OK] WANDB_API_KEY configured — Weave tracing available if installed")
    else:
        print("  [INFO] WANDB_API_KEY not set — all workflows run locally (no Weave)")


def main() -> int:
    failures = 0
    failures += 0 if _check_uv() else 1
    print()
    failures += 0 if _check_agentkaizen_cli() else 1
    print()
    _check_agent_clis()
    print()
    _check_wandb()
    print()
    if failures == 0:
        print("Setup OK.")
        return 0
    print(f"Setup incomplete. Fix the {failures} issue(s) above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
