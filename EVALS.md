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
- curated rows in `evals/cases.jsonl`
- generated draft cases created from past traces

### Datasets
The main offline eval dataset today is:
- `evals/cases.jsonl`

This file is useful, but it should be thought of as an early benchmark rather than a final mature benchmark. Over time, the project should evolve toward more intentional datasets organized by:
- core behaviors
- workflow compliance
- document steering regressions
- edge cases
- multimodal cases

### Scorers
The shared deterministic scorers live in `codex_scoring.py` and are used by `codex-eval`.

Current scorers:
- required substring presence
- forbidden substring absence
- maximum output length
- JSON parse validity
- required section presence
- file path citation presence
- token usage extraction

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

This model represents a candidate application configuration, not a provider SDK model wrapper. In practice, a variant means:
- a temporary copy of the repo
- optional file edits
- optional external files
- a particular Codex model/profile/sandbox/args setup

That is how this project uses Weave's model abstraction for evaluation-time app versioning.

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
1. Load the evaluation cases from `evals/cases.jsonl`
2. Build a baseline plus one or more variants
3. For each variant, create a temporary workspace
4. Copy the repo into that workspace
5. Apply candidate file edits or external file materialization
6. Run the same case set against that variant through `CodexVariantModel`
7. Score results with the shared scorers
8. Rank variants by quality score
9. Fail candidates when quality is similar but latency or token usage regress beyond configured thresholds

This makes document and config tuning measurable and comparable.

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

These are fast, deterministic, and easy to interpret.

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
This project is currently text-first. Image-bearing prompts are not preserved as first-class multimodal trace inputs in the current implementation.

### Redaction strategy
The project currently uses custom pre-upload redaction for interactive sessions instead of relying only on Weave's built-in PII redaction setting. That is mainly because this repo needs project-specific sanitization for:
- tokens and auth headers
- local filesystem paths
- usernames in paths
- session-specific metadata
- instruction boilerplate suppression

Built-in Weave PII redaction would still be a reasonable future improvement, but it would likely complement rather than replace the current logic.

## Recommended Next Steps
To improve evaluation quality over time:
- expand and categorize the eval datasets
- add harder regression cases from real failures
- introduce richer semantic scorers where needed
- add multimodal support if Codex session traces expose image-bearing inputs
- consider combining custom redaction with Weave's native PII redaction

## Related Files
- `codex_evals.py`
- `codex_scoring.py`
- `codex_casegen.py`
- `codex_interactive_sync.py`
- `codex_interactive_scoring.py`
- `evals/cases.jsonl`
