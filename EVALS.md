# Evaluation Strategy

## Purpose
This document explains how AgentKaizen evaluates changes to CLI-based AI agent behavior.

The key idea is simple: steering surfaces such as `AGENTS.md`, `README.md`, skills, and Codex config should be treated as testable product surfaces. We do not want to guess whether a change helped. We want to compare the baseline against candidate variants using the same prompts, the same scoring rules, and the same execution flow.

## What Gets Evaluated
AgentKaizen currently evaluates four related things:
- one-shot agent outputs (Codex and Claude Code)
- interactive session behavior after ingestion (Codex and Claude Code)
- candidate document or config variants in offline evals
- draft regression cases generated from recent traces

## Evaluation Building Blocks
### Prompts
Prompts in this project come from several places:
- direct prompts passed to `agentkaizen run`
- derived user tasks from interactive session traces
- curated rows in `evals/cases/*.jsonl`
- generated draft cases created from past traces

### Datasets
The main offline eval dataset now lives under `evals/cases/` and is split into:
- `core.jsonl`
- `workflow.jsonl`
- `docs-steering.jsonl`
- `regressions.jsonl`
- `multimodal.jsonl`

### Scorers
The shared deterministic scorers live in `src/agentkaizen/scoring.py` and are used by `agentkaizen eval`.

Current scorers:
- required substring presence
- forbidden substring absence
- minimum output length
- maximum output length
- JSON parse validity
- schema-aware JSON validation
- required section presence
- required content-group coverage
- file path citation presence
- token usage extraction

An optional **LLM-as-a-judge** scorer (`LLMJudgeScorer` in `src/agentkaizen/_llm_judge.py`) complements the deterministic layer. Enable it globally with `--judge-rubric "..."` on `agentkaizen eval`, or per-case via the `judge_rubric` field in JSONL cases. It runs another agent call (configurable runner) to evaluate semantic quality.

Built-in JSON/schema scorers depend on optional case fields:
- `response_schema` enables built-in JSON/schema validation (uses Weave scorers when available, local equivalents otherwise)
- datasets that do not include those fields should still run with the deterministic scorers only

These scorers are useful for:
- formatting and contract checks
- regression gating
- output policy enforcement

They are not sufficient for:
- semantic correctness
- answer usefulness
- code quality
- factual accuracy
- nuanced reasoning quality

So the current scorer layer should be treated as production-usable guardrails, not complete answer-quality evaluation.

### Models
Offline evals use `CodexVariantModel` (backed by `weave.Model` when Weave is installed, or `LocalModel` otherwise) in `src/agentkaizen/evals.py`.

This model represents an execution wrapper around a prepared candidate application configuration, not a provider SDK model wrapper. In practice, variant preparation means:
- a temporary copy of the repo
- optional file edits
- optional external files
- a particular Codex model/profile/sandbox/args setup

`CodexVariantModel` then executes that prepared workspace. The prepared config is the thing being compared over time.

## Two Tracking Modes
### 1. One-shot tracing
`agentkaizen run` runs a single agent invocation (Codex or Claude Code), parses the output, and stores:
- prompt
- command
- raw events
- final message
- usage
- guardrail results

This is useful when the unit of interest is one direct execution.

### 2. Full interactive-session ingestion
`agentkaizen session sync` reads local session files and reconstructs:
- user and assistant messages
- tool calls
- token usage
- completion state
- derived user task
- workflow analysis

For Codex sessions, files are read from `~/.codex/sessions/`. For Claude Code, `agentkaizen session sync --agent claude-code` reads `~/.claude/projects/<slug>/<uuid>.jsonl` and produces the same trace schema.

This is useful when the unit of interest is the whole session rather than a single final answer.

## Offline Eval Flow

> **Skill users**: For a quick A/B comparison without CLI setup, use `/optimize-coding-agent compare: [variant A] vs [variant B] on task: [...]` in your agent session. The full offline eval pipeline below provides multi-run dispersion stats and W&B Weave integration for CI use.

The offline eval command is `agentkaizen eval` (legacy alias: `codex-eval`).

The flow is:
1. Load the evaluation cases from `evals/cases/` or another JSONL suite path
2. Build a baseline plus one or more variants
3. For each variant, create a temporary workspace
4. Copy the repo into that workspace
5. Apply candidate file edits or external file materialization
6. Run the same case set against that variant through `CodexVariantModel`
7. Score results with the shared scorers
8. Rank variants by quality score
9. Fail candidates when quality is similar but latency or token usage regress beyond configured thresholds

This makes document and config tuning measurable and comparable.

### Multi-Run Benchmarks (`--runs N`)
By default, each variant is evaluated once. Use `--runs N` to run each variant N times and aggregate results:

```bash
uv run agentkaizen eval --runs 3 --cases evals/cases/core.jsonl --variant-file evals/variants/...
```

Each metric reports `mean ± stddev (n=N)`. Gating uses **conservative estimates**: `mean - stddev` for quality comparison and `mean + stddev` for regression detection. This reduces the chance of promoting a variant that won by a lucky single run.

When `--runs > 1`, the eval always uses the local path (Weave is bypassed). Single-run output is backward-compatible: `--runs 1` produces identical structure with no dispersion fields.

### Blind A/B Comparator (`--compare`)
Use `--compare` to run an LLM judge side-by-side on baseline and candidate outputs for each case, without the judge knowing which is which (position-bias elimination via random shuffle):

```bash
uv run agentkaizen eval --compare --show-outputs --cases evals/cases/... --variant-file evals/variants/...
```

Per-case output includes: winner, rubric scores (instruction adherence, completeness, efficiency, correctness on 1-5 scale), the judge's reasoning, winner strengths, and loser weaknesses.

**Comparator is report-only in v1** — it does not affect `gate_pass`. It is most useful when metric scores are similar and you need a qualitative tiebreaker.

Use `--compare-rubric "..."` to add custom evaluation criteria on top of the four default dimensions.

For language and style experiments such as "respond in Japanese" or "be more concise", prefer:
- `min_chars` when you need to prevent underspecified replies
- `max_chars` when brevity matters
- `required_content_groups` when you need one item from each concept bucket without forcing exact phrasing
- exact-match control prompts to catch over-application of the steering change
- curated prompt suites with deterministic checks rather than external-API-backed semantic scorers

## Interactive Scoring

> **Skill users**: Run `/optimize-coding-agent score my last session` in your agent session to score interactively without CLI setup. The heuristics below describe exactly what the skill's native scoring computes.

Interactive scoring has two layers.

### Deterministic heuristics
The heuristic layer uses signals extracted from session traces, such as:
- branch creation
- `uv` usage
- test execution
- lint execution
- format execution
- clarification questions
- user corrections
- tool call count
- execution errors

From those, the scorer derives:
- `task_completed`
- `task_success_estimate`
- `workflow_compliance`
- `user_friction`
- `efficiency`

The interactive scorer also returns additive breakdowns so the result is easier to audit:
- `task_success_factors`
- `friction_breakdown`
- `workflow_signal_breakdown`
- `efficiency_breakdown`

It also derives structured labels such as:
- `high_corrections`
- `clarification_needed`
- `high_tool_count`
- `execution_errors`
- `missing_branch`
- `missing_uv`
- `missing_tests`
- `missing_lint`
- `missing_format`

The scorer now distinguishes suspicious signals from definite workflow failures so high exploration cost does not automatically imply a workflow violation.

### Evidence-Based Claims
Both scoring paths now produce structured **Evidence-Based Claims** alongside the numeric scores. Claims are grouped by type:

- **process** — workflow steps: branch creation, test execution, linting
- **behavioral** — rule adherence: user corrections, unnecessary clarification questions
- **efficiency** — unnecessary actions, high tool call count

Each claim has: `type`, `claim` (human-readable assertion), `evidence` (grounding reference), `pass` (True/False), `severity` (high/medium/low for failures).

The **default heuristic path** synthesizes pseudo-claims from the signal detection results (e.g. `branch_created=True` → "Agent created feature branch before changes [✓]"`). These appear automatically with no extra configuration.

The **external judge path** grounds claims in specific evidence slices — turn-numbered summaries of up to 20 key messages and tool calls extracted from the trace — so claims can reference "Turn 3: git checkout -b feat/..." rather than just heuristic signals.

Claims are additive: existing friction signal and workflow gap lines are preserved unchanged.

### Optional external Codex judge (session scoring)
When `--scoring-backend external` is used for interactive session scoring, the project runs another `codex exec` call as a structured judge.

That judge:
- receives a prompt containing the derived `user_task`, `analysis_summary`, and up to 20 structured evidence slices (turn summaries of messages and tool calls)
- is told to treat the payload as untrusted data
- must return strict JSON with:
  - `task_success`
  - `user_friction`
  - `workflow_compliance`
  - `efficiency`
  - `optimization_relevance`
  - `reasoning`
  - `claims` (array of evidence-grounded claim objects)

The allowed `optimization_relevance` values are:
- `agents`
- `readme`
- `skill`
- `config`
- `none`

If the judge returns malformed JSON, the project retries once with a repair prompt. If that still fails, the scorer falls back to the deterministic local analysis path.

The external judge is slower and more failure-prone than the default structured local path. It should be treated as an optional audit mode, not the primary evaluator.

## Current Limitations
### Dataset maturity
The current case set is useful but still small and relatively simple. It should become more deliberately curated over time.

### Scorer depth
The current scorers are mostly structural and syntactic. They do not fully capture semantic quality.

### Multimodal coverage
This project preserves multimodal content blocks for one-shot prompts and interactive session messages. Scoring remains mostly text-first, but multimodal traces are now available for future eval expansion.

### Redaction strategy
The project uses hybrid redaction: custom pre-upload sanitization plus PII detection (Weave's ML-based redaction when installed, or local regex-based detection otherwise). The custom layer is still needed for:
- tokens and auth headers
- local filesystem paths
- usernames in paths
- session-specific metadata
- instruction boilerplate suppression

When Weave is installed, its built-in ML-based PII redaction complements the local regex and project-specific sanitization. When running locally without Weave, regex-based PII detection covers common patterns (emails, phones, SSNs, credit cards, API keys, bearer tokens) but may miss context-sensitive secrets.

## Recommended Next Steps
To improve evaluation quality over time:
- expand and categorize the eval datasets
- add harder regression cases from real failures
- introduce richer semantic scorers where needed
- expand multimodal eval cases beyond trace-fidelity checks
- continue calibrating task-aware workflow heuristics

## Related Files
- `src/agentkaizen/evals.py` (legacy shim: `codex_evals.py`)
- `src/agentkaizen/scoring.py` (legacy shim: `codex_scoring.py`)
- `src/agentkaizen/_llm_judge.py` — `LLMJudgeScorer` for eval case semantic scoring
- `src/agentkaizen/_local_eval.py` — `LocalEvaluation`, `evaluate_n()` for multi-run dispersion stats
- `src/agentkaizen/_comparator.py` — `ComparatorScorer` for blind A/B comparison
- `src/agentkaizen/casegen.py` (legacy shim: `codex_casegen.py`)
- `src/agentkaizen/session_sync.py` (legacy shim: `codex_interactive_sync.py`)
- `src/agentkaizen/session_scoring.py` (legacy shim: `codex_interactive_scoring.py`)
- `src/agentkaizen/claude_code_session.py`
- `evals/cases/`
