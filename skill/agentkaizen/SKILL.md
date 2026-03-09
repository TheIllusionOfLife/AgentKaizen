---
name: agentkaizen
description: "Use agentkaizen to measure and prove whether your AI coding agent actually follows instructions — not just to run it, but to verify it. Use this skill when: you want to trace a Codex or Claude Code run and check rule compliance (did it branch before work? stay within tool limits?); you changed AGENTS.md or config and need before/after evidence of whether it helped; a session used too many tool calls or failed to complete and you want to diagnose why; you need to generate regression eval cases from recorded traces. The trigger: any question about measuring, comparing, or verifying agent behavior — not writing instructions, not general debugging."
---

# AgentKaizen

AgentKaizen measures and improves CLI-based AI coding agent behavior by connecting steering inputs (AGENTS.md, skills, config) to measurable outcomes through tracing, scoring, and offline evaluation.

## Setup Check

```bash
uv run agentkaizen --help
```

If not installed:

```bash
git clone https://github.com/TheIllusionOfLife/AgentKaizen
cd AgentKaizen && uv sync --group dev
```

## Workflows

### 1. Trace a One-Shot Run

```bash
# Codex (default)
uv run agentkaizen run --prompt "Your task here"

# Claude Code
uv run agentkaizen run --agent claude-code --prompt "Your task here"

# With guardrails (exit 3 on violation)
uv run agentkaizen run --prompt "..." --must-contain "phrase" --guardrail-mode fail
```

Trace saved to `~/.agentkaizen/traces.jsonl`. Optionally streamed to W&B Weave if `WANDB_API_KEY` is set.

### 2. Sync & Score Sessions

```bash
# Sync Codex interactive sessions
uv run agentkaizen session sync --once

# Sync Claude Code sessions (~/.claude/projects/)
uv run agentkaizen session sync --agent claude-code --once

# Score a trace file
uv run agentkaizen session score --trace-file ~/.agentkaizen/traces.jsonl
```

`score` outputs a human-readable analysis: task, outcome, friction, workflow compliance, and recommendations.

### 3. Generate Eval Cases

```bash
uv run agentkaizen eval casegen --limit 20 --output evals/cases.generated.jsonl
```

Review and curate the output. Each case: `prompt`, optional `expected_output`, `must_contain`, `judge_rubric`. See `references/eval-format.md` for full schema.

### 4. Run Evals & Compare Variants

```bash
uv run agentkaizen eval \
  --cases evals/cases \
  --variant-file evals/variants/example.json
```

Ranks variants by score, latency, and token usage. Promote only variants that improve without regressions.

Useful flags: `--show-outputs`, `--judge-rubric "..."`, `--edit` (inline variant), `--allow-unsafe-scorer-file`.

See `references/eval-format.md` for case/variant JSONL format and scoring details.

## Config

Set persistent defaults in `pyproject.toml` to avoid repeating CLI flags:

```toml
[tool.agentkaizen]
agent = "claude-code"   # or "codex"
model = "claude-sonnet-4-6"
entity = "my-wandb-entity"
project = "my-project"
```

## Key Notes

- **W&B Weave is optional** — all workflows run locally without it.
- **LLM-as-a-judge** — add `--judge-rubric "..."` to `eval` for semantic scoring, or set per-case in JSONL.
- **Guardrail modes** — `warn` (default, exit 0) vs `fail` (exit 3 on violation).
- **Nested runs** — `agentkaizen run --agent claude-code` works from within an active Claude Code session (CLAUDECODE env var is stripped automatically).
