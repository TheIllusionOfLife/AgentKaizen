# User Workflow: Improving Codex Behavior with Weave

## Goal
Use measurable experiments to improve Codex outputs by iterating on foundational documents and config surfaces (for example `AGENTS.md`, `README.md`, skills, and Codex profile/config choices).

## Workflow
1. Define the objective
- Example: improve conciseness, reduce missed requirements, enforce output format.

2. Keep current docs as baseline
- Treat the current repository state as baseline behavior.

3. Create one or more variants
- Add candidate edits as variant JSON files under `evals/variants/`.
- Typical targets: `AGENTS.md`, `README.md`, external skill docs, and Codex config overrides.

4. Build/refresh eval cases
- Add real prompts to `evals/cases.jsonl`.
- Include checks: `must_contain`, `must_not_contain`, `max_chars`.
- Add structure checks when needed: `require_json`, `required_sections`, `require_file_paths`.

4.5 Generate candidate cases from recent traces (optional bootstrap)
```bash
uv run codex-casegen \
  --limit 20 \
  --output evals/cases.generated.jsonl
```
- Treat this as a draft; refine checks before relying on scores.
- Use `--redact-regex` when prompts may include sensitive strings.

4.6 Ingest and score interactive sessions
```bash
uv run codex-weave-sync-interactive --once
uv run codex-score-interactive --trace-file path/to/interactive-trace.json
```
- Use interactive traces to find repeated user corrections, workflow violations, and likely optimization surfaces.

5. Run offline comparison
```bash
uv run codex-eval \
  --cases evals/cases.jsonl \
  --variant-file evals/variants/<candidate>.json \
  --quality-similar-threshold 0.02 \
  --latency-regression-threshold 0.20 \
  --token-regression-threshold 0.20
```
- Compare baseline vs variants in Weave Evals.
- Gate candidates when quality is similar but latency/tokens regress.

6. Review metrics and traces
- Primary signal: scorer pass rate (`true_fraction`).
- Inspect trace outputs for quality, tone, regressions, and which surface (`AGENTS.md`, `README.md`, skill, config) appears responsible.

7. Promote the winner
- Apply the best-performing variant into real docs.
- Keep failed prompts as regression cases.

8. Monitor online behavior
```bash
uv run codex-weave \
  --prompt "<prompt>" \
  --must-contain "<rule>" \
  --required-section "<section>" \
  --require-file-paths \
  --guardrail-mode warn
```
- Use `warn` in exploration; switch to `fail` for strict automation.

## Practical Tips
- Change one major instruction at a time so attribution is clear.
- Prefer 10-20 high-value cases over many weak ones.
- Re-run evals after every meaningful doc update.
