# Eval Case & Variant Format

## Eval Case JSONL

Each line in an eval case file is a JSON object:

```jsonc
{
  "prompt": "Fix the bug in the auth module",          // required
  "expected_output": "Fixed by adding null check",     // optional: exact match scorer
  "must_contain": ["null check", "auth"],              // optional: substring scorers
  "must_not_contain": ["TODO", "placeholder"],         // optional
  "max_chars": 2000,                                   // optional: length scorer
  "require_json": false,                               // optional
  "response_schema": {"type": "object", ...},          // optional: JSON schema scorer
  "judge_rubric": "Did the agent fix root cause?",     // optional: per-case LLM judge
  "workspace": "path/to/workspace"                     // optional: isolated dir for run
}
```

Cases live in `evals/cases/` (one or more `.jsonl` files). Subdirectories are scanned recursively.

## Variant File JSON

```jsonc
{
  "variants": [
    {
      "name": "baseline",
      "agent": "codex",
      "model": "o3",
      "extra_args": []
    },
    {
      "name": "with-new-agents-md",
      "agent": "codex",
      "model": "o3",
      "workspace_overlay": "evals/overlays/new-agents-md/"  // files copied into workspace
    }
  ]
}
```

Fields per variant: `name` (required), `agent`, `model`, `extra_args`, `workspace_overlay`, `scorer_file`.

## Scorer Plugin

Supply a custom Python scorer via `--allow-unsafe-scorer-file path/to/scorer.py` or `scorer_file` in the variant. The file must define:

```python
def score(output: dict, prompt: str, **kwargs) -> dict:
    # output has keys: "text", "usage"
    # Return: {"pass": bool|None, "score": float|None, "reasoning": str}
    ...
```

## CLI Reference

```
agentkaizen run
  --prompt TEXT          Prompt text or '-' for stdin
  --agent {codex,claude-code}
  --model TEXT
  --must-contain TEXT    Repeatable
  --must-not-contain TEXT
  --max-chars INT
  --require-json
  --required-section TEXT
  --require-file-paths
  --guardrail-mode {warn,fail}
  --timeout-seconds INT

agentkaizen session sync
  --agent {codex,claude-code}
  --once                 Single pass and exit
  --poll-seconds INT     Continuous mode interval (default 60)
  --quiet-seconds INT    Skip sessions updated within N seconds (default 30)
  --session-root PATH    Override default session directory
  --state-file PATH      Override checkpoint state file
  --no-redaction         Disable PII redaction (not recommended)

agentkaizen session score
  --trace-file PATH      Required: path to trace JSONL

agentkaizen eval
  --cases PATH           Dir or file of case JSONL
  --variant-file PATH    Variant definitions JSON
  --show-outputs         Print full agent outputs
  --judge-rubric TEXT    Global LLM-as-a-judge rubric
  --allow-unsafe-scorer-file PATH
  --edit FIELD=VALUE     Inline variant override (repeatable)
  --prompt TEXT          Inline single-case run

agentkaizen eval casegen
  --limit INT            Max cases to generate (default 20)
  --output PATH          Output JSONL file
  --from-weave           Pull traces from W&B Weave instead of local
```

## Trace File Location

- One-shot traces: `~/.agentkaizen/traces.jsonl`
- Codex session sync state: `~/.codex/weave_sync_state.json`
- Claude Code session sync state: `~/.agentkaizen/claude_code_sync_state.json`
- Claude Code sessions: `~/.claude/projects/<slug>/<uuid>.jsonl`
