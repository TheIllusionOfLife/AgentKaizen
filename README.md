# AgentKaizen

Track and improve Codex CLI behavior with W&B Weave.

This repository provides:
- `codex-weave`: run `codex exec` with trace logging and optional online guardrails.
- `codex-eval`: run offline Weave Evals to compare baseline vs document variants (for example `AGENTS.md` changes).

## Requirements
- Python 3.12+
- `uv`
- Codex CLI (`codex`)
- W&B API key (`WANDB_API_KEY`)

## Setup
```bash
uv venv .venv
uv sync --group dev
```

The `WANDB_API_KEY` can be provided via the shell environment or a `.env.local` file:
```bash
WANDB_API_KEY=your_key_here
```

Default Weave target:
- Entity: `mukaiyuya-mukai-entertainment`
- Project: `AgentKaizen`

## Trace Codex Runs
```bash
uv run codex-weave --prompt "Say only: ok"
```

Read prompt from stdin:
```bash
echo "Say only: ok" | uv run codex-weave --prompt -
```

Pass Codex options:
```bash
uv run codex-weave \
  --prompt "review this repo" \
  --model o3 \
  --sandbox workspace-write \
  --profile default
```

## Online Guardrails
Guardrails are scored and attached to each trace.

```bash
uv run codex-weave \
  --prompt "how are you?" \
  --must-contain "ok" \
  --must-not-contain "forbidden" \
  --max-chars 120 \
  --required-section "Summary" \
  --require-file-paths \
  --guardrail-mode warn
```

- `--guardrail-mode warn`: print violations, keep exit code.
- `--guardrail-mode fail`: return exit code `3` on violations.
- `--require-json`: require valid JSON output.
- `--required-section <name>`: repeatable section-text requirement.
- `--require-file-paths`: require at least one file path citation.


## Generate Cases from Recent Traces
Create draft eval cases from recent `codex-weave` traces:

```bash
uv run codex-casegen \
  --limit 20 \
  --output evals/cases.generated.jsonl
```

Then review and refine generated checks (`must_contain`, `must_not_contain`, `max_chars`).

Optional redaction for sensitive prompt fragments:
```bash
uv run codex-casegen \
  --limit 20 \
  --output evals/cases.generated.jsonl \
  --redact-regex 'sk-[A-Za-z0-9]+' \
  --redact-regex '[\\w.-]+@[\\w.-]+'
```

## Offline Evals (Doc Impact)
Run baseline + variants on the same case set:

```bash
uv run codex-eval \
  --cases evals/cases.jsonl \
  --variant-file evals/variants/example_add_line_to_readme.json \
  --quality-similar-threshold 0.02 \
  --latency-regression-threshold 0.20 \
  --token-regression-threshold 0.20
```

Case file format (`evals/cases.jsonl`):
```json
{"prompt":"Say only: ok","must_contain":["ok"],"must_not_contain":["sorry"],"max_chars":40,"require_json":false,"required_sections":[],"require_file_paths":false}
```

Variant file format:
```json
{
  "name": "agents-extra-rule",
  "edits": [
    {
      "path": "AGENTS.md",
      "mode": "append",
      "text": "\nAlways include file references in implementation explanations.\n"
    }
  ]
}
```

`mode` supports `append`, `prepend`, and `replace`.

`codex-eval` exits with code `4` if a candidate fails regression gates (quality is similar but latency/tokens regress beyond threshold).

## Development
Run quality checks before committing:

```bash
uv run --group dev pytest
uv run --with ruff ruff check .
uv run --with ruff ruff format --check .
```
