"""Unified agentkaizen CLI entry point."""

from __future__ import annotations

import sys


# Module-level references to subcommand mains — patchable by tests.
def _run_main(argv=None):
    from agentkaizen.oneshot import main

    return main(argv)


def _eval_main(argv=None):
    from agentkaizen.evals import main

    return main(argv)


def _casegen_main(argv=None):
    from agentkaizen.casegen import main

    return main(argv)


def _session_sync_main(argv=None):
    from agentkaizen.session_sync import main

    return main(argv)


def _session_score_main(argv=None):
    from agentkaizen.session_scoring import main

    return main(argv)


_HELP = """\
agentkaizen — portable CLI evaluation tool for AI coding agents

Usage:
  agentkaizen run              One-shot traced agent run
  agentkaizen eval             Offline variant comparison eval
  agentkaizen eval casegen     Generate eval cases from recent traces
  agentkaizen session sync     Sync interactive sessions to Weave
  agentkaizen session score    Score an interactive session trace

Options:
  --help, -h    Show this help message

Pass --help after any subcommand for its own usage.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]

    if not args:
        print(_HELP, end="", file=sys.stderr)
        return 1

    if args[0] in ("--help", "-h"):
        print(_HELP, end="")
        return 0

    cmd = args[0]
    rest = args[1:]

    if cmd == "run":
        return _run_main(rest)

    if cmd == "eval":
        if rest and rest[0] == "casegen":
            return _casegen_main(rest[1:])
        return _eval_main(rest)

    if cmd == "session":
        if not rest:
            print(
                "agentkaizen session: missing subcommand\n"
                "  agentkaizen session sync    Sync interactive sessions\n"
                "  agentkaizen session score   Score an interactive trace\n",
                file=sys.stderr,
            )
            return 1
        if rest[0] == "sync":
            return _session_sync_main(rest[1:])
        if rest[0] == "score":
            return _session_score_main(rest[1:])
        print(
            f"agentkaizen session: unknown subcommand {rest[0]!r}\n"
            "  Use 'sync' or 'score'.\n",
            file=sys.stderr,
        )
        return 1

    print(
        f"agentkaizen: unknown command {cmd!r}\nRun 'agentkaizen --help' for usage.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
