# User Workflow: Improving Codex Behavior

This is a project-owned workflow guide for running the AgentKaizen loop. All workflows work locally without W&B. For W&B Weave integration (remote tracing and dashboards), set `WANDB_API_KEY`, `WANDB_ENTITY`, and `WANDB_PROJECT` in `.env.local` or your shell, as described in the repository [README.md](../../README.md).

## Goal
Use measurable experiments to improve Codex outputs by iterating on foundational documents and config surfaces (for example `AGENTS.md`, `README.md`, skills, and Codex profile/config choices).

## Recommended First Experience
If you want to demonstrate the full loop for a new user, start with the Japanese-response `AGENTS.md` example that already exists in this repo:

```bash
uv run agentkaizen eval \
  --cases evals/cases/language-steering.jsonl \
  --variant-file evals/variants/example_agents_japanese_response.json
```

Why this works well as an onboarding demo:
- the steering change is easy to explain
- the suite already contains control cases
- the output difference is visible in both metrics and raw traced outputs
- the result is interpretable: baseline partially misses the Japanese-targeted checks, while the variant improves them without breaking the explicit-English control

## Workflow
1. Define the objective
- Example: improve conciseness, reduce missed requirements, enforce output format.
- Keep the objective narrow enough that one document or config change could plausibly explain the outcome.

2. Keep current docs as baseline
- Treat the current repository state as baseline behavior.
- Do not bundle multiple unrelated doc edits into one candidate unless you are intentionally testing the bundle.

3. Create one or more variants
- Add candidate edits as variant JSON files under `evals/variants/`.
- Typical targets: `AGENTS.md`, `README.md`, external skill docs, and Codex config overrides.
- Prefer one major steering change per variant so attribution is clear.

4. Build/refresh eval cases
- Add real prompts to `evals/cases/`.
- Include checks: `must_contain`, `must_not_contain`, `max_chars`.
- Add `min_chars` only when a minimum answer length is genuinely part of success.
- Add structure checks when needed: `require_json`, `required_sections`, `require_file_paths`.
- Add optional semantic or schema targets only when needed:
  - `response_schema` for JSON/schema validation
- Add at least one control case when a steering change could overreach.
  - Example: if testing a Japanese-response instruction in `AGENTS.md`, keep one case that explicitly says `Respond in English...` so you can verify the repo instruction influences output without overriding direct user intent.

4.5 Generate candidate cases from recent traces (optional bootstrap)
```bash
uv run agentkaizen eval casegen \
  --limit 20 \
  --output evals/cases.generated.jsonl
```
- Treat this as a draft; refine checks before relying on scores.
- Use `--redact-regex` when prompts may include sensitive strings.

4.6 Ingest and score interactive sessions
```bash
uv run agentkaizen session sync --once
uv run agentkaizen session score --trace-file path/to/interactive-trace.json
```
- Use interactive traces to find repeated user corrections, workflow violations, likely optimization surfaces, and concrete recommended changes.
- The default scorer uses a fast structured subagent-style analysis path.
- Add `--scoring-backend external` when you want the slower `codex exec` audit flow as a second opinion before keeping or shipping a change.

5. Run offline comparison
```bash
uv run agentkaizen eval \
  --cases evals/cases \
  --variant-file evals/variants/<candidate>.json \
  --quality-similar-threshold 0.02 \
  --latency-regression-threshold 0.20 \
  --token-regression-threshold 0.20
```
- Compare baseline vs variants (locally or in Weave Evals when W&B is configured).
- Gate candidates when quality is similar but latency/tokens regress.
- `agentkaizen eval` runs variants in temp workspaces and automatically adds `--skip-git-repo-check` unless you already passed it.

Language-steering example:
```bash
uv run agentkaizen eval \
  --cases evals/cases/language-steering.jsonl \
  --variant-file evals/variants/example_agents_japanese_response.json
```

6. Review metrics and traces
- Do not rely on a single metric. Read the results in this order:
  1. Ranking: did the candidate beat baseline on `quality_score`?
  2. Gating: did it still `gate_pass`, or did it regress latency/tokens too much?
  3. Scorers: which checks moved, especially `score_contains_all`, `score_max_chars`, and any schema/structure checks that matter for this suite?
  4. Trace inspection: do the actual outputs look better, or did the candidate merely game the literal checks?
- Always inspect at least one or two actual per-case outputs before deciding to promote a change.
  - A good eval tells you both that the score moved and why it moved.
  - If the variant changed behavior but still missed a literal check, that may mean the steering change worked but the case needs refinement.
- Primary interpretation signals:
  - `quality_score`: overall usefulness against the active checks in the baseline suite
  - `quality_delta_vs_baseline`: whether the candidate meaningfully helped
  - `gate_pass`: whether the candidate is still efficient enough to keep
  - `optimization_relevance` from session scoring: which steering surface is the best next place to edit
- Use session scoring to answer a different question from evals:
  - evals ask: "Did candidate B beat baseline A on this prompt set?"
  - session scoring asks: "Which steering surface likely caused friction in this real session?"
- When both session backends agree on the same optimization surface, treat that as stronger evidence.
- When `subagent` and `external` disagree, inspect the trace before editing docs. Usually that means the workflow completed, but the evidence or execution quality was mixed.
- Prefer changes backed by both:
  - an eval improvement
  - a session-analysis signal pointing to the same surface

7. Promote the winner
- Apply the best-performing variant into real docs only when all of the following are true:
  - the candidate outranks baseline
  - `gate_pass` is still `True`
  - trace inspection matches the metric story
  - control cases still behave correctly
- Keep failed prompts as regression cases.
- If a candidate improves one target but breaks a control case, refine the wording instead of promoting it as-is.

8. Monitor online behavior
```bash
uv run agentkaizen run \
  --prompt "<prompt>" \
  --must-contain "<rule>" \
  --required-section "<section>" \
  --require-file-paths \
  --guardrail-mode warn
```
- Use `warn` in exploration; switch to `fail` for strict automation.

## How To Interpret Results
- If a variant improves `quality_score` and stays `gate_pass=True`, it is a serious candidate for promotion.
- If `quality_score` is similar but latency or tokens regress enough to fail the gate, keep the baseline.
- If one literal scorer improves but the output reads worse in traces, tighten the case checks before trusting the result.
- If session scoring says `optimization_relevance=agents`, edit `AGENTS.md` before touching broader surfaces like `README.md` or config.
- If session scoring says `readme`, improve setup or workflow docs before changing instruction text.
- If session scoring says `config`, test profile or default-runner adjustments before rewriting docs.

## Example Reading
- In a language-steering experiment, a baseline might partially satisfy Japanese-targeted cases while the `AGENTS.md` variant clearly improves `score_contains_all` and still passes the gate.
- That pattern means the repo-level instruction is influential enough to keep testing.
- If an explicit English control case still passes, the instruction is likely steering behavior without becoming too rigid.
- If a Japanese-targeted case still fails because the answer omitted a literal phrase like `W&B Weave`, inspect the traced output before discarding the variant.
- In that situation, the correct next step may be to refine the case rather than reject the steering change.
- The next workflow step is not "ship more language instructions everywhere."
- The next step is "promote the focused `AGENTS.md` change, keep the control case, and run another small eval on adjacent prompts."

## Practical Tips
- Change one major instruction at a time so attribution is clear.
- Prefer 10-20 high-value cases over many weak ones.
- Re-run evals after every meaningful doc update.
- Use the default `session score` backend for fast iteration and the `external` backend for final sanity checks.
- Treat old `codex-*` entry points as legacy compatibility wrappers; prefer the `agentkaizen` commands above for new workflows.
