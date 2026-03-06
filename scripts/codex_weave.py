# ruff: noqa: E402
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from codex_weave import main

if __name__ == "__main__":
    raise SystemExit(main())
