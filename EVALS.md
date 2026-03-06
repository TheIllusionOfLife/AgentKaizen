# Evaluation Strategy

## Purpose
This document explains how AgentKaizen evaluates changes to CLI-based AI agent behavior.

The key idea is simple: steering surfaces such as `AGENTS.md`, `README.md`, skills, and Codex config should be treated as testable product surfaces. We do not want to guess whether a change helped. We want to compare the baseline against candidate variants using the same prompts, the same scoring rules, and the same execution flow.

## What Gets Evaluated
AgentKaizen currently evaluates four related things:
- one-shot `codex exec` outputs
- interactive session behavior after ingestion
- candidate document or config variants in offline evals
- draft regression cases generated from recent traces

## Evaluation Building Blocks
### Prompts
Prompts in this project come from several places:
- direct prompts passed to `codex-weave`
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
The shared deterministic scorers live in `codex_scoring.py` and are used by `codex-eval`.

Current scorers:
- required substring presence
- forbidden substring absence
- maximum output length
- JSON parse validity
- schema-aware JSON validation
- required section presence
- file path citation presence
- token usage extraction

Built-in Weave scorers depend on optional case fields:
- `response_schema` enables built-in JSON/schema validation
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
Offline evals use `CodexVariantModel(weave.Model)` in `codex_evals.py`.

This model represents an execution wrapper around a prepared candidate application configuration, not a provider SDK model wrapper. In practice, variant preparation means:
- a temporary copy of the repo
- optional file edits
- optional external files
- a particular Codex model/profile/sandbox/args setup

`CodexVariantModel` then executes that prepared workspace. The prepared config is the thing being compared over time.

## Two Tracking Modes
### 1. One-shot tracing
`codex-weave` runs a single `codex exec --json`, parses the event stream, and stores:
- prompt
- command
- raw events
- final message
- usage
- guardrail results

This is useful when the unit of interest is one direct execution.

### 2. Full interactive-session ingestion
`codex-weave-sync-interactive` reads local Codex session files and reconstructs:
- user and assistant messages
- tool calls
- token usage
- completion state
- derived user task
- workflow analysis

This is useful when the unit of interest is the whole session rather than a single final answer.

## Offline Eval Flow
The offline eval command is `codex-eval`.

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

For language and style experiments such as "respond in Japanese" or "be more concise", prefer:
- `max_chars` when brevity matters
- exact-match control prompts to catch over-application of the steering change
- curated prompt suites with deterministic checks rather than external-API-backed semantic scorers

## Interactive Scoring
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
- `workflow_compliance`
- `user_friction`
- `efficiency`

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

### Optional external Codex judge
When `--scoring-backend external` is used, the project runs another `codex exec` call as a structured judge.

That judge:
- receives a prompt containing the derived `user_task` and `analysis_summary`
- is told to treat the payload as untrusted data
- must return strict JSON with:
  - `task_success`
  - `user_friction`
  - `workflow_compliance`
  - `efficiency`
  - `optimization_relevance`
  - `reasoning`

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
The project uses hybrid redaction: custom pre-upload sanitization plus Weave's built-in PII redaction. The custom layer is still needed for:
- tokens and auth headers
- local filesystem paths
- usernames in paths
- session-specific metadata
- instruction boilerplate suppression

Built-in Weave PII redaction is active in the current runtime, and it complements rather than replaces the current logic.

## Recommended Next Steps
To improve evaluation quality over time:
- expand and categorize the eval datasets
- add harder regression cases from real failures
- introduce richer semantic scorers where needed
- expand multimodal eval cases beyond trace-fidelity checks
- continue calibrating task-aware workflow heuristics

## Related Files
- `codex_evals.py`
- `codex_scoring.py`
- `codex_casegen.py`
- `codex_interactive_sync.py`
- `codex_interactive_scoring.py`
- `evals/cases/`
