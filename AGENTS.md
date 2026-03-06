# Repository Guidelines

## Project Structure & Module Organization
This repository is a lightweight Python toolkit for tracing and evaluating Codex CLI behavior with W&B Weave.
- Core runtime modules: `codex_weave.py` (exec trace wrapper), `codex_interactive_sync.py` (interactive session ingester), `codex_evals.py` (offline eval runner), `codex_scoring.py` (shared scorers).
- CLI entry scripts are exposed through `pyproject.toml` (`codex-weave`, `codex-weave-sync-interactive`, `codex-eval`, `codex-casegen`).
- Evaluation assets live under `evals/`:
  - `evals/cases.jsonl` for prompt test cases
  - `evals/variants/*.json` for document-edit variants
- Tests live in `tests/` and mirror module responsibilities.

## Build, Test, and Development Commands
Use `uv` for all Python workflow tasks.
- `uv run codex-weave --prompt "Say only: ok"`: run Codex with Weave tracing.
- `uv run codex-weave-sync-interactive --once`: ingest completed interactive Codex sessions from local session files.
- `uv run codex-eval --cases evals/cases.jsonl --variant-file <file>`: compare baseline vs variant docs using Weave Evals.
- `uv run codex-casegen --limit 20 --output evals/cases.generated.jsonl`: draft eval cases from recent traces.
- `uv run --group dev pytest`: run all tests.
- `uv run --with ruff ruff check .`: lint.
- `uv run --with ruff ruff format --check .`: formatting check.

## Coding Style & Naming Conventions
- Follow Python 3.12+ style with 4-space indentation and type hints for public functions.
- Use `snake_case` for functions, files, and variables.
- Keep modules focused (single responsibility); share scoring logic via `codex_scoring.py`.
- Run Ruff lint + format checks before submitting changes.

## Testing Guidelines
- Framework: `pytest`.
- Add tests for new behavior and regression paths (especially CLI argument handling and exit codes).
- Test files should be named `tests/test_<module>.py`; test names should describe expected behavior.
- Prefer fast unit tests with monkeypatching for subprocess/Weave interactions.

## Commit & Pull Request Guidelines
Git history is currently minimal (`Initial commit`), so use clear Conventional Commit style going forward (for example, `feat: add guardrail fail mode`).
- Keep commits scoped to one logical change.
- PRs should include: purpose, key behavior changes, test evidence (commands + results), and any W&B/CLI usage notes.

## Security & Configuration Tips
- Keep secrets in `.env.local` (`WANDB_API_KEY=...`) and never commit them.
- Validate guardrails with `--guardrail-mode warn` before enforcing `fail` in automation.
