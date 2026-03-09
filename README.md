# AgentKaizen

Measure and improve how CLI-based AI coding agents behave. Works locally out of the box; optionally integrates with W&B Weave for remote tracing and dashboards.

## Why This Project Exists
Users of tools like Codex can steer agent behavior through many different surfaces:
- global `AGENTS.md`
- project `AGENTS.md`
- agent skills
- `README.md`
- Codex config and profiles
- other repo-specific documents

Those surfaces matter, but it is usually hard to tell which change actually helped. This project exists to connect those steering inputs to measurable outcomes — locally by default, with optional W&B Weave integration for remote tracing and dashboards.

In practice, AgentKaizen helps you:
- trace Codex CLI runs
- trace Claude Code CLI runs
- score outputs with lightweight guardrails
- ingest and analyze interactive Codex sessions
- ingest and analyze interactive Claude Code sessions
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

### Install
```bash
uv sync --group dev-minimal      # minimal install (local-only, no W&B)
uv sync --group dev              # full dev install (includes weave)
```

To install the package with W&B Weave support (package consumers, not repo checkout):
```bash
pip install agentkaizen[weave]   # or: uv add agentkaizen[weave]
```

All workflows work without W&B. When Weave is not installed or `WANDB_API_KEY` is not set, AgentKaizen runs in local-only mode: traces are saved to `~/.agentkaizen/traces.jsonl`, evaluations run locally, and PII redaction uses built-in regex patterns.

### Environment Variables (Optional — W&B Weave)
For remote tracing and dashboards, set the W&B variables in your shell profile or in `.env.local`:

```bash
export WANDB_API_KEY=your_key_here
export WANDB_ENTITY=your-team-or-username
export WANDB_PROJECT=your-weave-project
```

When all three are set and `weave` is installed, commands automatically trace to both the local log and W&B. The entity can come from `--entity`, `WANDB_ENTITY`, `.env.local`, or your logged-in W&B account, but the most reliable setup is to keep both `WANDB_ENTITY` and `WANDB_PROJECT` in `.env.local`.

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

Run with Claude Code instead of Codex:

```bash
uv run agentkaizen run --agent claude-code --prompt "Say only: ok"
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

### Ingest interactive Claude Code sessions
```bash
uv run agentkaizen session sync --agent claude-code --once
```

Sessions are read from `~/.claude/projects/<slug>/<uuid>.jsonl`. The sync state is persisted at `~/.agentkaizen/claude_code_sync_state.json`.

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

### Recommended First Demo
If you are trying AgentKaizen for the first time, start with the Japanese-response `AGENTS.md` experiment:

```bash
uv run agentkaizen eval \
  --cases evals/cases/language-steering.jsonl \
  --variant-file evals/variants/example_agents_japanese_response.json
```

Why this is a good first demo:

- it changes one clear steering surface: `AGENTS.md`
- it includes control cases such as `Say only: ok`
- it includes an explicit-English control so you can verify the change steers default behavior without overriding direct user intent
- the output change is easy to see in both the ranking summary and the traced per-case outputs

### How to read results
Use evals and session scoring together:

- `quality_score` answers: did this variant help on the active case checks?
- `quality_delta_vs_baseline` answers: did it help enough to beat the current docs?
- `gate_pass` answers: did it stay efficient enough on latency and tokens?
- `optimization_relevance` from `agentkaizen session score` answers: which steering surface should you edit next?

Practical rule of thumb:

- Promote a variant when it outranks baseline, still has `gate_pass: True`, and the traced outputs actually look better.
- Keep the baseline when quality is similar but the candidate regresses latency or token usage enough to fail the gate.
- Add at least one control case for instruction-steering experiments so you can confirm the change helps without becoming too rigid.
- Use the default `session score` backend for fast iteration and the `external` backend as a slower second opinion before shipping a change.

Do not stop at the ranking summary:

- if using W&B Weave, open the matching eval calls and inspect the traced per-case outputs for baseline and variant
- verify that the changed outputs look better for the reason you intended, not just because they happened to satisfy a literal scorer
- if a case still fails, check whether the problem is the model behavior or the case design

### Legacy entry points (soft-deprecated)
The old `codex-weave`, `codex-eval`, `codex-casegen`, `codex-weave-sync-interactive`, and `codex-score-interactive` entry points still work and delegate to the same implementations. Prefer the `agentkaizen` subcommands for new workflows.

## How AgentKaizen Works
AgentKaizen provides a complete local evaluation and tracing pipeline:

1. **Local tracing** — All agent runs and session ingestions are logged to `~/.agentkaizen/traces.jsonl` as structured JSONL entries.

2. **Local evaluation** — `LocalEvaluation` runs the same case set against multiple candidate variants and summarizes scorer results, matching the exact schema used by W&B Weave evaluations.

3. **Shared scorers** — Translate desired agent behavior into measurable checks such as required text, forbidden text, output length, JSON validity, file path citations, and token usage.

4. **Local PII redaction** — Regex-based detection of emails, phone numbers, SSNs, credit cards, API keys, and bearer tokens. Best-effort but covers common patterns.

When W&B Weave is installed and configured, AgentKaizen additionally:
- Traces to W&B via `weave.init()` and `@weave.op()`
- Uses `weave.Evaluation()` for remote eval tracking with dashboard support
- Uses Weave's ML-based PII redaction (complementing the local regex layer)

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

Models in this repo are application-level model wrappers, not provider SDK wrappers. `agentkaizen eval` uses `CodexVariantModel` (backed by `weave.Model` when Weave is installed, or `LocalModel` otherwise) to represent a candidate agent behavior running inside a temporary workspace with specific config and document variants.

#### 3. Image prompts
This project now preserves multimodal prompt structure for one-shot `codex exec` runs and interactive session ingestion. Flattened text fields are still retained for backwards compatibility, but traces also keep ordered content blocks and a `modalities` summary.

#### 4. App versioning
This project uses model classes (`weave.Model` when available, `LocalModel` otherwise) in offline evals to represent candidate app behavior. Each variant is effectively a versioned Codex application setup:
- temporary workspace contents
- Codex model and profile settings
- candidate document or config edits

This is a lightweight use of app versioning focused on comparison during evals, not a full model-registry workflow.

#### 5. PII redaction
This repo uses hybrid redaction for traced content: custom sanitization for repo-specific secrets and path cleanup, plus optional Weave PII redaction when installed. When Weave is not available, local regex-based PII detection covers common patterns (emails, phones, SSNs, credit cards, API keys, bearer tokens). The project-specific layer still handles:
- API keys and bearer tokens
- filesystem paths and usernames
- session-specific metadata cleanup
- suppression of large instruction boilerplate when deriving the user task

When Weave is installed, its built-in ML-based redaction is enabled for one-shot and interactive trace uploads, complementing the local regex and project-specific sanitization.

## Troubleshooting
- If a command says `WANDB_PROJECT` is missing, add both `WANDB_PROJECT` and `WANDB_ENTITY` to `.env.local` or pass `--entity`/`--project` explicitly.
- If a command says `WANDB_API_KEY` is missing, you can either set the key for W&B integration or run in local-only mode (no action needed).
- If an eval is meant to validate structured JSON output, make sure the relevant case rows include `response_schema`.

## Architecture
The core flow is:

1. Run or ingest Codex activity into local traces (and optionally W&B Weave).
2. Score those traces with guardrails or interactive-session heuristics.
3. Generate reusable cases from real traces.
4. Compare candidate steering changes, such as `AGENTS.md` edits, against the baseline.
5. Promote the winning changes back into the real repo docs and instructions.

Key modules (all under `src/agentkaizen/`):
- [`cli.py`](./src/agentkaizen/cli.py) — unified `agentkaizen` entry point
- [`oneshot.py`](./src/agentkaizen/oneshot.py) — one-shot traced agent run (`agentkaizen run`)
- [`session_sync.py`](./src/agentkaizen/session_sync.py) — interactive session ingestion
- [`claude_code_session.py`](./src/agentkaizen/claude_code_session.py) — parses Claude Code JSONL sessions (`~/.claude/projects/`): discovery, trace building, sync flow
- [`session_scoring.py`](./src/agentkaizen/session_scoring.py) — interactive trace scoring
- [`evals.py`](./src/agentkaizen/evals.py) — offline variant comparison
- [`casegen.py`](./src/agentkaizen/casegen.py) — draft case generation from traces
- [`scoring.py`](./src/agentkaizen/scoring.py) — shared scorer functions
- [`core.py`](./src/agentkaizen/core.py) — shared infra: JSONL parser, PII redaction, W&B env
- [`_weave_compat.py`](./src/agentkaizen/_weave_compat.py) — `HAS_WEAVE` flag, `weave_init()`, `weave_op()` shims
- [`_local_eval.py`](./src/agentkaizen/_local_eval.py) — local evaluation framework (`LocalEvaluation`, `LocalModel`, `LocalScorer`)
- [`_trace_log.py`](./src/agentkaizen/_trace_log.py) — local JSONL trace persistence and querying
- [`_pii.py`](./src/agentkaizen/_pii.py) — local regex-based PII redaction
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
