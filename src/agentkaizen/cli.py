"""Unified agentkaizen CLI entry point (stub — full implementation in Phase 3)."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print(
        "agentkaizen — portable CLI evaluation tool for AI coding agents\n"
        "\n"
        "Available commands (use legacy entry points for now):\n"
        "  codex-weave              One-shot traced run\n"
        "  codex-eval               Offline variant comparison\n"
        "  codex-casegen            Generate eval cases from traces\n"
        "  codex-weave-sync-interactive  Sync interactive sessions\n"
        "  codex-score-interactive  Score interactive traces\n"
        "\n"
        "Unified subcommand interface coming in Phase 3.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
