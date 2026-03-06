# Project Structure

## Top-Level Layout
- `README.md`: human-oriented introduction and usage
- `AGENTS.md`: repository-specific agent instructions
- `PRODUCT.md`: product goals and user context
- `TECH.md`: technical stack and constraints
- `STRUCTURE.md`: repository layout and conventions
- `codex_weave.py`: traced `codex exec` wrapper
- `codex_evals.py`: offline eval runner for document and config variants
- `codex_casegen.py`: draft case generation from recent traces
- `codex_interactive_sync.py`: local interactive-session ingestion
- `codex_interactive_scoring.py`: interactive trace analysis and scoring
- `codex_scoring.py`: shared scorer functions
- `evals/`: eval datasets and variant definitions
- `tests/`: test suite mirroring runtime modules
- `scripts/`: thin wrapper scripts
- `docs/`: secondary project docs and reference material

## Docs Layout
- `docs/workflows/`: project-owned workflow guides
- `docs/reference/`: imported or vendor-oriented reference docs that are not the main source of truth for repo behavior

## Module Boundaries
- Add new logic to an existing module when it clearly belongs to that module's responsibility.
- Create a new module only when the responsibility is distinct and would otherwise blur boundaries.
- Keep scoring rules out of CLI entry points when they can live in `codex_scoring.py`.
- Keep ingestion separate from analysis for interactive sessions.
- Keep one-shot tracing concerns in `codex_weave.py`.
- Keep full-session reconstruction and redaction concerns in `codex_interactive_sync.py`.
- Keep offline evaluation-time model wrappers in `codex_evals.py`.

## Tests
- Test files should mirror the module they cover:
  - `tests/test_codex_weave.py`
  - `tests/test_codex_evals.py`
  - `tests/test_codex_casegen.py`
  - `tests/test_codex_interactive_sync.py`
  - `tests/test_codex_interactive_scoring.py`
  - `tests/test_codex_scoring.py`
- Shared test helpers belong in `tests/conftest.py`

## Naming and Import Conventions
- Use `snake_case`
- Prefer explicit imports from local modules
- Keep CLI parser and `main()` logic near the entry point module that owns the command

## When To Reorganize Further
The current repo intentionally keeps core modules at the root for easy inspection. A package refactor should happen only if:
- import boundaries become confusing
- shared internal helpers grow substantially
- release packaging needs become more complex

Until then, prefer improving docs and boundaries over moving all runtime code into a package.
