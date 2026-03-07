# AgentKaizen

Measure and improve how CLI-based AI coding agents behave, using W&B Weave.

## Why This Project Exists
Users of tools like Codex can steer agent behavior through many different surfaces:
- global `AGENTS.md`
- project `AGENTS.md`
- agent skills
- `README.md`
- Codex config and profiles
- other repo-specific documents

Those surfaces matter, but it is usually hard to tell which change actually helped. This project exists to connect those steering inputs to measurable outcomes with W&B Weave.

In practice, AgentKaizen helps you:
- trace Codex CLI runs
- score outputs with lightweight guardrails
- ingest and analyze interactive Codex sessions
- compare instruction and document variants with offline evals
- turn real traces into reusable regression cases

## What Is W&B Weave?
W&B Weave is an observability and evaluation toolkit for AI applications. It is especially useful when you need to trace model behavior, inspect failures, and compare candidate improvements systematically instead of relying on intuition.

This project uses Weave mainly for:
- traces: logging Codex runs and interactive sessions
- evals: comparing baseline behavior against candidate document or config changes
- scorers: grading output quality, structure, and token usage
- model evaluation workflows: running the same case set against multiple variants

If you are new to Weave, start here:
- Main site: https://wandb.ai/site/weave/
- Documentation: https://docs.wandb.ai/weave

## Quick Start
### Requirements
- Python 3.12+
- `uv`
- Codex CLI (`codex`) or Claude Code CLI (`claude`)
- A W&B account and API key

### Environment Variables
Set the required W&B variables in your shell profile or in `.env.local`:

```bash
WANDB_API_KEY=your_key_here
WANDB_ENTITY=your-team-or-username
WANDB_PROJECT=your-weave-project
```

For a shell session, you can export them like this:

```bash
export WANDB_API_KEY=your_key_here
export WANDB_ENTITY=your-team-or-username
export WANDB_PROJECT=your-weave-project
```

All commands in this repo require a W&B project. The entity can come from `--entity`, `WANDB_ENTITY`, `.env.local`, or your logged-in W&B account. If you do not want to set environment variables, pass `--entity` and `--project` explicitly on each command.

AgentKaizen-specific environment variables (override `[tool.agentkaizen]` defaults when pyproject.toml is absent):
- `AGENTKAIZEN_AGENT`: agent runner to use (`codex` or `claude-code`)
- `AGENTKAIZEN_MODEL`: model name passed to the agent CLI
- `AGENTKAIZEN_ENTITY`: W&B entity (also falls back to `WANDB_ENTITY`)
- `AGENTKAIZEN_PROJECT`: W&B project (also falls back to `WANDB_PROJECT`)
- `AGENTKAIZEN_TIMEOUT_SECONDS`: timeout per agent invocation
- `AGENTKAIZEN_CASES`: default eval case directory
- `AGENTKAIZEN_SCORING_BACKEND`: scoring backend (`subagent` or `external`)

Useful optional Weave environment variables:
- `WANDB_BASE_URL`: use a custom or self-hosted W&B base URL
- `WEAVE_PARALLELISM`: tune eval concurrency for larger `codex-eval` runs
- `WEAVE_PRINT_CALL_LINK=false`: suppress noisy call-link output in scripted or CI environments
- `WEAVE_LOG_LEVEL`: increase logging when debugging Weave integration issues
- `WEAVE_DISABLED=true`: disable Weave tracing entirely for local dry runs or troubleshooting

### Install
```bash
uv sync --group dev
```

### Repo defaults (`[tool.agentkaizen]`)
AgentKaizen reads project-level defaults from `pyproject.toml` before any command runs. This is the primary steering surface for choosing the agent and tuning eval behavior — you set it once per project rather than repeating flags on every command.

```toml
[tool.agentkaizen]
agent = "codex"          # or "claude-code"
model = "o4-mini"        # passed to the agent CLI
cases = "evals/cases"    # default eval case directory
timeout_seconds = 300
scoring_backend = "subagent"
```

Precedence: CLI flags > `[tool.agentkaizen]` > `AGENTKAIZEN_*` env vars > `WANDB_*` env vars (entity/project only) > built-in defaults. Changing `agent` here switches every `agentkaizen run` and `agentkaizen eval` invocation to the specified agent without needing to pass `--agent` each time. Config is loaded by `src/agentkaizen/config.py` and merged into the eval/run config before the eval loop starts.

## Main Workflows
### Trace a one-shot agent run
```bash
uv run agentkaizen run --prompt "Say only: ok"
```

Attach one or more images to the initial prompt:

```bash
uv run agentkaizen run \
  --prompt "Describe the UI issue in this screenshot" \
  --image ./artifacts/screenshot.png
```

Read the prompt from stdin:

```bash
echo "Say only: ok" | uv run agentkaizen run --prompt -
```

### Ingest interactive Codex sessions
```bash
uv run agentkaizen session sync --once
```

Continuous polling mode:

```bash
uv run agentkaizen session sync \
  --poll-seconds 15 \
  --quiet-seconds 30
```

### Score an interactive trace
```bash
uv run agentkaizen session score --trace-file path/to/interactive-trace.json
```

Structured JSON output:

```bash
uv run agentkaizen session score \
  --trace-file path/to/interactive-trace.json \
  --json
```

### Generate eval cases from recent traces
```bash
uv run agentkaizen eval casegen \
  --limit 20 \
  --output evals/cases.generated.jsonl
```

### Compare document or config variants
```bash
uv run agentkaizen eval \
  --cases evals/cases \
  --variant-file evals/variants/example_add_line_to_readme.json \
  --quality-similar-threshold 0.02 \
  --latency-regression-threshold 0.20 \
  --token-regression-threshold 0.20
```

Run the Japanese-response `AGENTS.md` experiment:

```bash
uv run agentkaizen eval \
  --cases evals/cases/language-steering.jsonl \
  --variant-file evals/variants/example_agents_japanese_response.json
```

`agentkaizen eval` runs each variant inside a temporary workspace and, unless you already passed it, automatically adds `--skip-git-repo-check` to the Codex invocation.

### Legacy entry points (soft-deprecated)
The old `codex-weave`, `codex-eval`, `codex-casegen`, `codex-weave-sync-interactive`, and `codex-score-interactive` entry points still work and delegate to the same implementations. Prefer the `agentkaizen` subcommands for new workflows.

## How AgentKaizen Uses Weave
The important mapping is:

1. `weave.init(...)`
Connects the current CLI command to a W&B project.

2. `@weave.op()`
Wraps important operations so their inputs, outputs, and metadata become traces.

3. `weave.Evaluation(...)`
Runs the same case set against multiple candidate variants and summarizes scorer results.

4. Shared scorers
Translate desired agent behavior into measurable checks such as required text, forbidden text, output length, JSON validity, file path citations, and token usage.

This is what makes the repo useful: it turns prompt and documentation tuning into an evaluation loop instead of guesswork.

### Capability Mapping
#### 1. Two tracking modes
This project uses Weave tracing in two distinct modes:
- one-shot tracing for agent runs through `agentkaizen run`
- full-session ingestion for interactive Codex sessions through `agentkaizen session sync`

The one-shot mode stores structured prompt content, command, event stream, final message, usage, and guardrail results. The interactive mode reconstructs an entire session from local Codex session files and stores structured message content, tool calls, usage, derived task text, and workflow analysis.

The important difference is what each mode answers:
- one-shot and offline eval flows answer: "did variant B beat baseline A on this prompt set?"
- interactive scoring answers: "what happened in this real session, how well did it go, and which optimization surface should we adjust next?"

In other words, one-shot/offline eval is for controlled comparison across variants, while interactive ingestion and scoring is for diagnosing a single real session and turning it into the next hypothesis to test.

#### 2. Prompts, datasets, scorers, and models
Prompts in this repo come from:
- direct `codex-weave` prompts
- derived user tasks from interactive sessions
- eval case prompts in `evals/cases/*.jsonl`
- generated draft cases from past traces

Datasets in this repo are the eval case suite files under `evals/cases/`, plus draft case files generated from traces.

Scorers in this repo are shared functions and Weave built-ins that check:
- required text
- forbidden text
- minimum output length
- output length
- JSON validity
- schema conformance
- required sections
- required content groups
- file path citations
- token usage

Built-in scorers are enabled only when the eval dataset contains the fields they need:
- `response_schema` activates built-in JSON/schema validation
- datasets without those optional fields still run with the deterministic scorers

Models in this repo are application-level Weave models, not provider SDK wrappers. `agentkaizen eval` uses `CodexVariantModel(weave.Model)` to represent a candidate agent behavior running inside a temporary workspace with specific config and document variants.

#### 3. Image prompts
This project now preserves multimodal prompt structure for one-shot `codex exec` runs and interactive session ingestion. Flattened text fields are still retained for backwards compatibility, but traces also keep ordered content blocks and a `modalities` summary.

#### 4. App versioning with `weave.Model`
This project uses `weave.Model` in offline evals to represent candidate app behavior. Each variant is effectively a versioned Codex application setup:
- temporary workspace contents
- Codex model and profile settings
- candidate document or config edits

This is a lightweight use of app versioning focused on comparison during evals, not a full model-registry workflow.

#### 5. PII redaction
This repo uses hybrid redaction for traced content: custom sanitization for repo-specific secrets and path cleanup, plus Weave's built-in PII redaction support. The project-specific layer still handles:
- API keys and bearer tokens
- filesystem paths and usernames
- session-specific metadata cleanup
- suppression of large instruction boilerplate when deriving the user task

Weave's built-in redaction is enabled for one-shot and interactive trace uploads, but it complements rather than replaces the project-specific sanitization above.

## Troubleshooting
- If a command says `WANDB_PROJECT` is missing, add it to your shell or `.env.local`.
- If a command says `WANDB_API_KEY` is missing or invalid, refresh the key in `.env.local` or your shell session.
- If an eval is meant to validate structured JSON output, make sure the relevant case rows include `response_schema`.

## Architecture
The core flow is:

1. Run or ingest Codex activity into Weave traces.
2. Score those traces with guardrails or interactive-session heuristics.
3. Generate reusable cases from real traces.
4. Compare candidate steering changes, such as `AGENTS.md` edits, against the baseline.
5. Promote the winning changes back into the real repo docs and instructions.

Key modules (all under `src/agentkaizen/`):
- [`cli.py`](./src/agentkaizen/cli.py) — unified `agentkaizen` entry point
- [`oneshot.py`](./src/agentkaizen/oneshot.py) — one-shot traced agent run (`agentkaizen run`)
- [`session_sync.py`](./src/agentkaizen/session_sync.py) — interactive session ingestion
- [`session_scoring.py`](./src/agentkaizen/session_scoring.py) — interactive trace scoring
- [`evals.py`](./src/agentkaizen/evals.py) — offline variant comparison
- [`casegen.py`](./src/agentkaizen/casegen.py) — draft case generation from traces
- [`scoring.py`](./src/agentkaizen/scoring.py) — shared scorer functions
- [`core.py`](./src/agentkaizen/core.py) — shared infra: JSONL parser, PII redaction, W&B env
- [`runners/`](./src/agentkaizen/runners/) — `AgentRunner` protocol + `CodexRunner`, `ClaudeCodeRunner`

## Repository Docs
For deeper context, see:
- [AGENTS.md](./AGENTS.md): repo-specific instructions for coding agents
- [EVALS.md](./EVALS.md): evaluation strategy, datasets, scorers, heuristics, and judge flow
- [PRODUCT.md](./PRODUCT.md): product purpose, users, and goals
- [TECH.md](./TECH.md): stack, tooling, and constraints
- [STRUCTURE.md](./STRUCTURE.md): file layout and architectural boundaries
- [docs/workflows/user_workflow.md](./docs/workflows/user_workflow.md): recommended evaluation workflow

Reference material:
- [docs/reference/openai.md](./docs/reference/openai.md)
- [docs/reference/anthropic.md](./docs/reference/anthropic.md)

## Development
Run the standard checks before submitting changes:

```bash
uv run --group dev pytest
uv run --group dev ruff check .
uv run --group dev ruff format --check .
```

For more on supported Weave environment variables, see:
- https://docs.wandb.ai/weave/guides/core-types/env-vars
