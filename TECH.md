# Technology Stack

## Primary Stack
- Language: Python 3.12+
- Package and environment management: `uv`
- Observability and evals: `weave`
- Test framework: `pytest`
- Lint and formatting: `ruff`
- CI: GitHub Actions

## Runtime Dependencies
- Codex CLI (`codex`) is required for the main workflows
- W&B credentials are required for live tracing and eval submission:
  - `WANDB_API_KEY`
  - `WANDB_ENTITY`
  - `WANDB_PROJECT`

Useful optional Weave and W&B environment variables:
- `WANDB_BASE_URL`
- `WEAVE_PARALLELISM`
- `WEAVE_PRINT_CALL_LINK`
- `WEAVE_LOG_LEVEL`
- `WEAVE_DISABLED`

## Key Technical Choices
- Single-file top-level modules keep each CLI entry point easy to inspect
- `weave.op()` is used to capture traced operations
- `weave.Evaluation()` is used for offline comparison of variants
- Temporary workspaces isolate candidate doc and config edits during evals
- Shared scorer functions centralize output checks and reduce drift

## How Weave Is Used Here
### Tracing
There are two tracing modes in this project:
- one-shot `codex exec` tracing in `codex_weave.py`
- full interactive-session ingestion in `codex_interactive_sync.py`

The first tracks a single Codex execution. The second reconstructs an entire local Codex session into a structured trace payload.

### Prompts, datasets, scorers, and models
- Prompts come from direct CLI prompts, derived interactive tasks, and eval case files.
- Datasets are JSONL case files used for offline evals.
- Scorers are shared Python functions wrapped for Weave evaluation.
- Models are app-level Weave models. `CodexVariantModel` represents a variant of Codex behavior running in a specific temporary workspace with a specific config.

### App versioning
This repo uses `weave.Model` for evaluation-time app versioning, not for a full standalone model registry. A variant is effectively "this repo state plus these edits plus this Codex config," evaluated against a shared case set.

### Multimodal support
The current implementation is text-first. It does not preserve uploaded images or other multimodal prompt content as structured Weave inputs.

### Redaction strategy
The project currently performs custom pre-upload redaction for interactive traces. That choice was made because the repo needs to sanitize:
- tokens and auth headers
- local filesystem paths
- usernames embedded in paths
- session-specific instruction boilerplate

Weave's built-in PII redaction could still be added later, but it would be additive rather than a complete replacement.

### Operational environment variables
This project currently relies on environment variables for operational Weave behavior instead of hardcoded runtime settings. That is usually the right fit for:
- CI-friendly output suppression with `WEAVE_PRINT_CALL_LINK=false`
- eval concurrency tuning with `WEAVE_PARALLELISM`
- alternate W&B hosts through `WANDB_BASE_URL`
- temporary local tracing disablement through `WEAVE_DISABLED=true`

## Constraints
- The repo is designed around Codex CLI output and local Codex session files
- The project assumes reproducible CLI workflows rather than notebook-first workflows
- No database or web service is maintained by this repo; Weave is the main persistence and analysis layer
- Tests should remain fast and mostly unit-level, using monkeypatching instead of real networked runs

## Preferred Tooling
- Use `uv` rather than ad hoc virtualenv or pip workflows
- Use `ruff` rather than multiple overlapping lint/format tools
- Use `pytest` for all automated tests

## Compatibility Notes
- Current CI uses Python 3.12
- `weave` behavior can evolve over time, so integration points should stay narrow and tested
- CLI behavior changes should preserve clear stderr messages and explicit exit codes
