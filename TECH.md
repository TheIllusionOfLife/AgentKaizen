# Technology Stack

## Primary Stack
- Language: Python 3.12+
- Package and environment management: `uv`
- Observability and evals: `weave`
- Test framework: `pytest`
- Lint and formatting: `ruff`
- CI: GitHub Actions

## Runtime Dependencies
- Codex CLI (`codex`) or Claude Code CLI (`claude`) — at least one is required depending on the configured agent
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
- `src/agentkaizen/` package layout with root-level backward-compat shims for legacy entry points
- `AgentRunner` protocol in `runners/` isolates agent-specific subprocess logic from calling code
- `weave.op()` is used to capture traced operations
- `weave.Evaluation()` is used for offline comparison of variants
- Temporary workspaces isolate candidate doc and config edits during evals
- Shared scorer functions in `scoring.py` centralize output checks and reduce drift
- `[tool.agentkaizen]` in pyproject.toml provides config defaults; CLI flags always win

## How Weave Is Used Here
### Tracing
There are two tracing modes in this project:
- one-shot agent run tracing in `agentkaizen.oneshot` (`agentkaizen run`)
- full interactive-session ingestion in `agentkaizen.session_sync` (`agentkaizen session sync`)

The first tracks a single agent execution via `AgentRunner`. The second reconstructs an entire local Codex session into a structured trace payload.

### Prompts, datasets, scorers, and models
- Prompts come from direct CLI prompts, derived interactive tasks, and eval case files.
- Datasets are JSONL case files used for offline evals.
- Scorers are shared Python functions in `agentkaizen.scoring`, wrapped for Weave evaluation.
- Models are app-level Weave models. `CodexVariantModel` represents a variant of agent behavior running in a specific temporary workspace with a specific config.

### App versioning
This repo uses `weave.Model` for evaluation-time app versioning, not for a full standalone model registry. A variant is effectively "this repo state plus these edits plus this Codex config," evaluated against a shared case set.

### Multimodal support
The current implementation preserves structured multimodal prompt and message blocks for text and image inputs while keeping flattened text fields for compatibility with existing scoring and summaries.

### Redaction strategy
The project performs hybrid redaction for traced payloads: custom pre-upload sanitization plus Weave's built-in PII redaction. The custom layer is still needed to sanitize:
- tokens and auth headers
- local filesystem paths
- usernames embedded in paths
- session-specific instruction boilerplate

Weave's built-in PII redaction is enabled in the current runtime, and it remains additive rather than a complete replacement.

### Operational environment variables
This project currently relies on environment variables for operational Weave behavior instead of hardcoded runtime settings. That is usually the right fit for:
- CI-friendly output suppression with `WEAVE_PRINT_CALL_LINK=false`
- eval concurrency tuning with `WEAVE_PARALLELISM`
- alternate W&B hosts through `WANDB_BASE_URL`
- temporary local tracing disablement through `WEAVE_DISABLED=true`

## Constraints
- The repo is designed around CLI agent output (Codex and Claude Code) and local Codex session files
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
