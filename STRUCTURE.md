# Project Structure

## Top-Level Layout
- `README.md`: human-oriented introduction and usage
- `AGENTS.md`: repository-specific agent instructions
- `PRODUCT.md`: product goals and user context
- `TECH.md`: technical stack and constraints
- `STRUCTURE.md`: repository layout and conventions
- `src/agentkaizen/`: canonical package (see below)
- `codex_weave.py` etc.: backward-compat shims — re-export `main` from `agentkaizen.*` for legacy entry points
- `evals/`: eval datasets and variant definitions
- `tests/`: test suite
- `scripts/`: thin wrapper scripts
- `docs/`: secondary project docs and reference material
- `skill/`: Agent Skill distribution (`skill/agentkaizen/SKILL.md` + `skill/agentkaizen.skill`)
- `archive/`: stale hackathon artifacts (not part of the active codebase)

## Package Layout (`src/agentkaizen/`)
- `cli.py`: unified `agentkaizen` entry point with subcommand dispatch
- `core.py`: shared infra — JSONL parser, PII redaction, W&B env resolution, prompt building
- `oneshot.py`: one-shot traced agent run (`agentkaizen run`)
- `evals.py`: offline variant comparison using temporary workspaces
- `casegen.py`: draft case generation from recent Weave traces
- `session_sync.py`: local interactive-session ingestion into Weave traces
- `claude_code_session.py`: parses Claude Code JSONL sessions (`~/.claude/projects/`): discovery, trace building, sync flow
- `session_scoring.py`: interactive trace analysis and scoring
- `scoring.py`: shared deterministic scorer functions
- `config.py`: load `[tool.agentkaizen]` from pyproject.toml; merge with CLI args
- `runners/`: `AgentRunner` protocol + `CodexRunner`, `ClaudeCodeRunner`, registry

## Docs Layout
- `docs/workflows/`: project-owned workflow guides
- `docs/reference/`: imported or vendor-oriented reference docs that are not the main source of truth for repo behavior

## Module Boundaries
- Add new logic to an existing module when it clearly belongs to that module's responsibility.
- Create a new module only when the responsibility is distinct and would otherwise blur boundaries.
- Keep scoring rules out of CLI entry points when they can live in `src/agentkaizen/scoring.py`.
- Keep ingestion separate from analysis for interactive sessions.
- Keep one-shot tracing concerns in `src/agentkaizen/oneshot.py`.
- Keep full-session reconstruction and redaction concerns in `src/agentkaizen/session_sync.py`.
- Keep offline evaluation-time model wrappers in `src/agentkaizen/evals.py`.
- All agent subprocess calls must go through `agentkaizen.runners.get_runner()`. Implement new agent runners in `runners/` and register them in `runners/registry.py`.

## Tests
- Test files cover the canonical `agentkaizen.*` modules using the alias trick:
  ```python
  import agentkaizen.oneshot as codex_weave  # alias for test patchability
  ```
- Current test files:
  - `tests/test_codex_weave.py` — covers `agentkaizen.oneshot` (and `agentkaizen.core`)
  - `tests/test_codex_evals.py` — covers `agentkaizen.evals`
  - `tests/test_codex_casegen.py` — covers `agentkaizen.casegen`
  - `tests/test_codex_interactive_sync.py` — covers `agentkaizen.session_sync` (shim name; canonical module is `session_sync.py`)
  - `tests/test_codex_interactive_scoring.py` — covers `agentkaizen.session_scoring` (shim name; canonical module is `session_scoring.py`)
  - `tests/test_codex_scoring.py` — covers `agentkaizen.scoring`
  - `tests/test_cli.py` — covers `agentkaizen.cli`
  - `tests/test_config.py` — covers `agentkaizen.config`
  - `tests/test_runners.py` — covers `agentkaizen.runners`
  - `tests/test_claude_code_session.py` — covers `agentkaizen.claude_code_session`
  - `tests/test_claude_code_e2e.py` — live E2E tests for Claude Code session ingestion (skipped in CI)
- Shared test helpers belong in `tests/conftest.py`

## Naming and Import Conventions
- Use `snake_case`
- Prefer explicit imports from local modules
- Keep CLI parser and `main()` logic near the entry point module that owns the command

## When To Reorganize Further
The repo uses a `src/agentkaizen/` layout. New runtime code belongs in the package, not at the root. Add new modules to `src/agentkaizen/` when the responsibility is distinct. Add new agent runners under `src/agentkaizen/runners/` and register them in `registry.py`.
