# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

AgentKaizen measures and improves CLI-based AI coding agent behavior using W&B Weave. It connects steering inputs (AGENTS.md, README.md, skills, Codex config) to measurable outcomes through tracing, scoring, and offline evaluation. Supports both Codex and Claude Code agents.

## Commands

```bash
# Install
uv sync --group dev

# Tests
uv run --group dev pytest
uv run --group dev pytest tests/test_codex_scoring.py          # single file
uv run --group dev pytest tests/test_codex_scoring.py::test_fn  # single test

# Lint & format
uv run --group dev ruff check .
uv run --group dev ruff format --check .

# Primary CLI (unified entry point)
uv run agentkaizen --help
uv run agentkaizen run --prompt "Say only: ok"
uv run agentkaizen eval --cases evals/cases --variant-file evals/variants/example.json
uv run agentkaizen eval casegen --limit 20 --output evals/cases.generated.jsonl
uv run agentkaizen session sync --once
uv run agentkaizen session score --trace-file path/to/trace.json

# Legacy entry points (still work, soft-deprecated)
uv run codex-weave --prompt "Say only: ok"
uv run codex-weave-sync-interactive --once
uv run codex-score-interactive --trace-file path/to/trace.json
uv run codex-casegen --limit 20 --output evals/cases.generated.jsonl
uv run codex-eval --cases evals/cases --variant-file evals/variants/example.json

# Build package
uv build
```

CI runs `pytest`, `ruff check .`, and `ruff format --check .` via `uv run --group dev` (see `.github/workflows/ci.yml`).

## Architecture

`src/agentkaizen/` is the canonical package. Root-level `codex_*.py` files are backward-compat shims that re-export `main` for legacy entry points.

### Package modules

| Module | Responsibility |
|--------|----------------|
| `core.py` | Shared infra: JSONL parser, PII redaction, W&B env resolution, prompt building |
| `oneshot.py` | One-shot traced agent run CLI (`agentkaizen run`) |
| `evals.py` | Offline variant comparison: workspaces, `CodexVariantModel`, scoring/ranking |
| `casegen.py` | Generate draft eval cases from recent Weave traces |
| `session_sync.py` | Ingest local Codex sessions into Weave traces |
| `session_scoring.py` | Score interactive session traces (heuristics + optional external judge) |
| `scoring.py` | Deterministic scorer functions (substring, length, JSON, schema, sections) |
| `cli.py` | Unified `agentkaizen` entry point with subcommand dispatch |
| `config.py` | Load `[tool.agentkaizen]` from pyproject.toml; merge with CLI args |
| `runners/` | `AgentRunner` protocol + `CodexRunner`, `ClaudeCodeRunner`, registry |

### Data flow

```text
codex exec / interactive sessions / claude -p
        |
   agentkaizen run / agentkaizen session sync   (trace into Weave)
        |
   agentkaizen session score                    (score real sessions)
   agentkaizen eval casegen                     (turn traces into eval cases)
        |
   agentkaizen eval                             (compare variants offline)
        |
   promote winning changes back to repo docs
```

### Key patterns

- `agentkaizen.core` is the shared foundation — all other modules import env resolution, PII utils, and JSONL parser from it.
- Agent execution goes through `agentkaizen.runners.get_runner(name, **kwargs)` — never call subprocess directly.
- `AgentRunner` protocol: `run(prompt, *, workspace, timeout_seconds) -> AgentResult`; `build_command(prompt) -> list[str]`.
- Config precedence: CLI flags > `[tool.agentkaizen]` in pyproject.toml > env vars > defaults.
- Eval cases live in `evals/cases/*.jsonl`; variant definitions in `evals/variants/*.json`.
- Tests import from `agentkaizen.*` using the alias trick: `import agentkaizen.oneshot as codex_weave`. This keeps `monkeypatch.setattr(codex_weave, "subprocess", ...)` pointing at the canonical module.
- `codex exec --json` returns JSONL event streams. Always use `parse_codex_jsonl()` from `agentkaizen.core`.

## Non-Obvious Behaviors

- Interactive sync seeds state on first run and uploads nothing initially (prevents backfilling entire history).
- `codex-eval` / `agentkaizen eval` auto-adds `--skip-git-repo-check` unless already supplied.
- Optional eval case fields (`response_schema`) activate Weave built-in scorers; datasets without them must still work with deterministic scorers only.
- `.env.local` is a supported source for `WANDB_API_KEY`, `WANDB_ENTITY`, `WANDB_PROJECT`, and `WANDB_BASE_URL`.
- Redaction is hybrid: custom sanitization (tokens, paths, usernames) plus Weave built-in PII redaction.
- `ClaudeCodeRunner` uses `claude -p prompt --output-format json` and parses `{"type": "result", "result": "..."}`.
- Token usage is not available from Claude Code's JSON output mode (future: `stream-json` mode).

## Conventions

- Python 3.12+, type hints on public functions, `snake_case` everywhere.
- Use `uv` for all Python workflows. Do not use pip directly.
- Use `ruff` for linting and formatting.
- Conventional Commit messages (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- Do not hardcode personal W&B entity/project values anywhere.
- Keep CLI changes synchronized across README.md, AGENTS.md, and tests.
- Implement new agent runners in `src/agentkaizen/runners/` and register in `registry.py`.
