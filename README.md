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
- Codex CLI (`codex`)
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

All commands in this repo require a W&B entity and project. If you do not want to set environment variables, pass `--entity` and `--project` explicitly on each command.

### Install
```bash
uv venv .venv
uv sync --group dev
```

## Main Workflows
### Trace a `codex exec` run
```bash
uv run codex-weave --prompt "Say only: ok"
```

Read the prompt from stdin:

```bash
echo "Say only: ok" | uv run codex-weave --prompt -
```

### Ingest interactive Codex sessions
```bash
uv run codex-weave-sync-interactive --once
```

Continuous polling mode:

```bash
uv run codex-weave-sync-interactive \
  --poll-seconds 15 \
  --quiet-seconds 30
```

### Score an interactive trace
```bash
uv run codex-score-interactive --trace-file path/to/interactive-trace.json
```

Structured JSON output:

```bash
uv run codex-score-interactive \
  --trace-file path/to/interactive-trace.json \
  --json
```

### Generate eval cases from recent traces
```bash
uv run codex-casegen \
  --limit 20 \
  --output evals/cases.generated.jsonl
```

### Compare document or config variants
```bash
uv run codex-eval \
  --cases evals/cases.jsonl \
  --variant-file evals/variants/example_add_line_to_readme.json \
  --quality-similar-threshold 0.02 \
  --latency-regression-threshold 0.20 \
  --token-regression-threshold 0.20
```

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
- one-shot tracing for `codex exec` runs through `codex-weave`
- full-session ingestion for interactive Codex sessions through `codex-weave-sync-interactive`

The one-shot mode stores a single prompt, command, event stream, final message, usage, and guardrail results. The interactive mode reconstructs an entire session from local Codex session files and stores messages, tool calls, usage, derived task text, and workflow analysis.

#### 2. Prompts, datasets, scorers, and models
Prompts in this repo come from:
- direct `codex-weave` prompts
- derived user tasks from interactive sessions
- eval case prompts in `evals/cases.jsonl`
- generated draft cases from past traces

Datasets in this repo are the eval case files used by `codex-eval`, plus draft case files generated from traces.

Scorers in this repo are shared functions that check:
- required text
- forbidden text
- output length
- JSON validity
- required sections
- file path citations
- token usage

Models in this repo are application-level Weave models, not provider SDK wrappers. `codex-eval` uses `CodexVariantModel(weave.Model)` to represent a candidate Codex behavior running inside a temporary workspace with specific config and document variants.

#### 3. Image prompts
W&B Weave can support multimodal traces, but this project is currently text-first. One-shot tracing accepts a text prompt, and interactive session ingestion flattens message content to text. That means image-bearing prompts are not preserved as first-class multimodal inputs in the current implementation.

#### 4. App versioning with `weave.Model`
This project uses `weave.Model` in offline evals to represent candidate app behavior. Each variant is effectively a versioned Codex application setup:
- temporary workspace contents
- Codex model and profile settings
- candidate document or config edits

This is a lightweight use of app versioning focused on comparison during evals, not a full model-registry workflow.

#### 5. PII redaction
This repo currently uses custom pre-upload redaction for interactive sessions rather than Weave's built-in PII redaction setting. The main reason is that the repo needs domain-specific sanitization beyond generic PII detection, including:
- API keys and bearer tokens
- filesystem paths and usernames
- session-specific metadata cleanup
- suppression of large instruction boilerplate when deriving the user task

Built-in Weave redaction would still be a reasonable future improvement, but it would complement rather than replace the project-specific sanitization already implemented here.

## Architecture
The core flow is:

1. Run or ingest Codex activity into Weave traces.
2. Score those traces with guardrails or interactive-session heuristics.
3. Generate reusable cases from real traces.
4. Compare candidate steering changes, such as `AGENTS.md` edits, against the baseline.
5. Promote the winning changes back into the real repo docs and instructions.

Key entry points:
- [codex_weave.py](/Users/yuyamukai/dev/AgentKaizen/codex_weave.py)
- [codex_interactive_sync.py](/Users/yuyamukai/dev/AgentKaizen/codex_interactive_sync.py)
- [codex_interactive_scoring.py](/Users/yuyamukai/dev/AgentKaizen/codex_interactive_scoring.py)
- [codex_evals.py](/Users/yuyamukai/dev/AgentKaizen/codex_evals.py)
- [codex_casegen.py](/Users/yuyamukai/dev/AgentKaizen/codex_casegen.py)
- [codex_scoring.py](/Users/yuyamukai/dev/AgentKaizen/codex_scoring.py)

## Repository Docs
For deeper context, see:
- [AGENTS.md](/Users/yuyamukai/dev/AgentKaizen/AGENTS.md): repo-specific instructions for coding agents
- [EVALS.md](/Users/yuyamukai/dev/AgentKaizen/EVALS.md): evaluation strategy, datasets, scorers, heuristics, and judge flow
- [PRODUCT.md](/Users/yuyamukai/dev/AgentKaizen/PRODUCT.md): product purpose, users, and goals
- [TECH.md](/Users/yuyamukai/dev/AgentKaizen/TECH.md): stack, tooling, and constraints
- [STRUCTURE.md](/Users/yuyamukai/dev/AgentKaizen/STRUCTURE.md): file layout and architectural boundaries
- [docs/workflows/user_workflow.md](/Users/yuyamukai/dev/AgentKaizen/docs/workflows/user_workflow.md): recommended evaluation workflow

Reference material:
- [docs/reference/openai.md](/Users/yuyamukai/dev/AgentKaizen/docs/reference/openai.md)
- [docs/reference/anthropic.md](/Users/yuyamukai/dev/AgentKaizen/docs/reference/anthropic.md)

## Development
Run the standard checks before submitting changes:

```bash
uv run --group dev pytest
uv run --with ruff ruff check .
uv run --with ruff ruff format --check .
```
