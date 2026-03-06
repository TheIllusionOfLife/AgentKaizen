# Repository Guidelines

## Purpose
This repository exists to improve CLI-based AI agent behavior with measurable feedback loops. The main product question is not just "can Codex solve a task?" but "which steering surface changed the behavior, and did it help enough to keep?"

Important steering surfaces in this repo include:
- `AGENTS.md`
- `README.md`
- eval cases and variants
- external skill documents
- Codex CLI configuration and profiles

## Required Environment
Live Weave workflows require all of the following:
- `WANDB_API_KEY`
- `WANDB_ENTITY`
- `WANDB_PROJECT`

Do not hardcode personal W&B entity or project values in code, docs, examples, or tests.

Useful optional environment variables:
- `WANDB_BASE_URL` for custom or self-hosted W&B deployments
- `WEAVE_PARALLELISM` for tuning eval concurrency
- `WEAVE_PRINT_CALL_LINK=false` for CI or other non-interactive runs
- `WEAVE_LOG_LEVEL` when debugging Weave integration behavior
- `WEAVE_DISABLED=true` for local runs where tracing should be bypassed

## Commands You Should Use
Use `uv` for all Python workflows.

Common commands:
- `uv sync --group dev`
- `uv run codex-weave --prompt "Say only: ok"`
- `uv run codex-weave-sync-interactive --once`
- `uv run codex-score-interactive --trace-file path/to/interactive-trace.json`
- `uv run codex-casegen --limit 20 --output evals/cases.generated.jsonl`
- `uv run codex-eval --cases evals/cases.jsonl --variant-file evals/variants/<file>.json`
- `uv run --group dev pytest`
- `uv run --with ruff ruff check .`
- `uv run --with ruff ruff format --check .`

## Architecture Rules
- Keep top-level modules focused by responsibility.
- Put shared output and quality checks in `codex_scoring.py`.
- Keep `codex_weave.py` responsible for traced `codex exec` runs.
- Keep `codex_interactive_sync.py` responsible for turning local session files into structured Weave traces.
- Keep `codex_interactive_scoring.py` responsible for analyzing interactive trace payloads, not for ingestion.
- Keep `codex_evals.py` responsible for offline variant comparison using temporary workspaces.
- Keep `codex_casegen.py` responsible for turning past traces into draft evaluation cases.

## Coding Style
- Python 3.12+
- Type hints for public functions
- `snake_case` for functions, variables, and modules
- Prefer small, composable helpers over large multi-purpose functions
- Follow existing CLI patterns for exit codes and stderr messaging

## Testing
- Framework: `pytest`
- Preferred command: `uv run --group dev pytest`
- Lint: `uv run --with ruff ruff check .`
- Format check: `uv run --with ruff ruff format --check .`

When changing CLI behavior:
- add or update tests for exit codes and error messages
- keep README examples aligned with the real CLI contract
- verify CI still runs the same commands documented in the repo

## Repository Etiquette
- Create a feature branch before making changes
- Use clear Conventional Commit style messages
- Keep each commit scoped to one logical change
- Never push directly to `main`
- Do not merge unless explicitly asked

## Non-Obvious Behaviors
- W&B entity and project must be passed explicitly or provided through `WANDB_ENTITY` and `WANDB_PROJECT`.
- `codex exec --json` returns JSONL event streams, not a single JSON object. Reuse `parse_codex_jsonl()` instead of inventing a new parser.
- Interactive sync seeds the state file on the first run and uploads nothing on that initial pass. This prevents backfilling the entire local history unexpectedly.
- Interactive trace redaction is enabled by default. Preserve that default unless there is a strong reason to change it.
- Offline evals compare variants inside temporary workspaces. Do not mutate the real repo as part of evaluation logic.
- Interactive scoring has two paths: a default structured local analysis path and an older external Codex-judge path. Prefer the default path unless you are intentionally changing the judge behavior.

## Common Gotchas
- Do not reintroduce personal or repo-owner-specific defaults for Weave targets.
- Do not duplicate the same test environment values in many files. Use shared helpers from `tests/conftest.py`.
- Do not change CLI flags or required env vars without updating:
  - `README.md`
  - `AGENTS.md`
  - tests
  - any affected workflow docs
- Do not treat imported vendor reference docs as canonical project behavior. Project-owned docs in the root and `docs/workflows/` are the source of truth for this repo.

## How To Avoid Past Review Problems
- Keep docs, tests, and implementation synchronized when changing behavior.
- Prefer one shared helper over repeated literals in tests and examples.
- Keep evaluation logic measurable and explicit; avoid hidden defaults that make results hard to reproduce.
- When adding a new steering surface, document how it participates in the eval loop so future contributors can reason about impact.
