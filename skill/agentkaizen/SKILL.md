---
name: agentkaizen
description: "Use agentkaizen to measure and prove whether your AI coding agent actually follows instructions — not just to run it, but to verify it. Use this skill when: you want to trace a Codex or Claude Code run and check rule compliance (did it branch before work? stay within tool limits?); you changed AGENTS.md or config and need before/after evidence of whether it helped; a session used too many tool calls or failed to complete and you want to diagnose why; you need to generate regression eval cases from recorded traces; you want a qualitative blind comparison of two agent outputs without metric bias. The trigger: any question about measuring, comparing, or verifying agent behavior — not writing instructions, not general debugging."
allowed-tools: Bash(uv:*) Bash(python:*) Read Write
---

# AgentKaizen

AgentKaizen measures and improves CLI-based AI coding agent behavior by connecting steering inputs (AGENTS.md, skills, config) to measurable outcomes through tracing, scoring, and offline evaluation.

## Setup Check

From the AgentKaizen repo root:

```bash
python skill/agentkaizen/scripts/check_setup.py
```

Exits 0 on success; prints specific fix instructions per failure.

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

# Score a trace file (default heuristic backend)
uv run agentkaizen session score --trace-file path/to/trace.json

# Score with external Codex judge (slower, grounded claims)
uv run agentkaizen session score --scoring-backend external --trace-file path/to/trace.json
```

`score` outputs: task, outcome, friction signals, workflow gaps, metrics, and an **Evidence-Based Claims** section — structured pass/fail assertions about agent behavior grouped by type (process, behavioral, efficiency). The default heuristic backend synthesizes claims from signal detection instantly; `--scoring-backend external` grounds claims in specific turn evidence from the trace.

### 3. Generate Eval Cases

```bash
uv run agentkaizen eval casegen --limit 20 --output evals/cases.generated.jsonl
```

Review and curate the output. Each case: `prompt`, optional `expected_output`, `must_contain`, `judge_rubric`. See `references/eval-format.md` for full schema.

### 4. Run Evals & Compare Variants

**Basic comparison:**

```bash
uv run agentkaizen eval \
  --cases evals/cases \
  --variant-file evals/variants/example.json
```

**Multi-run for dispersion-aware gating** (recommended before promoting):

```bash
uv run agentkaizen eval \
  --runs 3 \
  --cases evals/cases/core.jsonl \
  --variant-file evals/variants/example.json
```

Reports `quality_score: 0.850 ± 0.032 (n=3)`. Gating uses `mean - stddev` (conservative) to avoid promoting based on a lucky run. Zero stddev on a failing scorer means the problem is systematic, not noise.

**Blind A/B comparison** (qualitative, report-only):

```bash
uv run agentkaizen eval \
  --compare \
  --show-outputs \
  --cases evals/cases \
  --variant-file evals/variants/example.json
```

An LLM judge evaluates each baseline/candidate output pair without knowing which is which (random shuffle eliminates position bias). Per-case verdict: winner, rubric scores (instruction adherence, completeness, efficiency, correctness 1-5), reasoning, strengths, weaknesses. Use `--compare-rubric "..."` for custom criteria. Does **not** affect `gate_pass`.

**After every eval**, the output automatically includes an **Interpretation** block and prioritized **Suggested Next Actions** — no delta means the wrong steering surface was edited; failing `contains_pass` with `stddev=0` is deterministic not noise; etc.

Useful flags: `--show-outputs`, `--judge-rubric "..."`, `--edit` (inline variant), `--allow-unsafe-scorer-file`.

See `references/eval-format.md` for case/variant JSONL format and scoring details.

## Subagent Workflows

Standalone agent prompt templates — no CLI required. Work with Codex or Claude.

| Agent | File | When to use |
|-------|------|-------------|
| Behavioral Grader | `agents/grader.md` | Grade whether a session met behavioral expectations (branching, testing, tool limits). Input: score JSON from `session score --json`. |
| A/B Comparator | `agents/comparator.md` | Blind qualitative comparison of two agent outputs. Works without CLI. Report-only — does not affect `gate_pass`. |
| Pattern Analyzer | `agents/analyzer.md` | Find systematic patterns across multiple session scores. Input: directory of score JSONs. |

Invoke by telling your agent: "Read `agents/grader.md` and follow those instructions with these expectations: [...]"

Each agent writes output JSON to the current directory: `grading.json`, `comparison.json`, `analysis.json`.

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
- **`--runs N` forces local eval path** — Weave is bypassed; a notice is printed.
- **`--compare` is report-only** — comparator verdicts inform the user but never change `gate_pass`.
- **LLM-as-a-judge** — add `--judge-rubric "..."` to `eval` for semantic scoring, or set per-case in JSONL.
- **Guardrail modes** — `warn` (default, exit 0) vs `fail` (exit 3 on violation).
- **Nested runs** — `agentkaizen run --agent claude-code` works from within an active Claude Code session (CLAUDECODE env var is stripped automatically).
- **Interpretation is automatic** — after every eval, a human-readable analysis and next-action list are printed below the ranking table.
