---
name: agentkaizen
description: "Use agentkaizen to measure and prove whether your AI coding agent actually follows instructions. Works natively — no installation required. Use this skill when: you want to score a recent Codex or Claude Code session and check rule compliance (did it branch before work? stay within tool limits?); you changed AGENTS.md or config and need before/after evidence; a session used too many tool calls or failed to complete; you want a qualitative blind comparison of two agent outputs. Trigger: any question about measuring, comparing, or verifying agent behavior."
allowed-tools: Bash Read Write Glob
---

# AgentKaizen

Measure and improve CLI-based AI coding agent behavior. Works entirely through agent-native tools (Read/Glob/Bash/Write) — no Python install or CLI required.

---

## Section 1 — Detect Environment

First, determine which agent context is active:

```bash
echo $CLAUDECODE
```

- Non-empty → **Claude Code** context: sessions at `~/.claude/projects/`, one-shot via `claude -p`
- Empty → check for Codex: `command -v codex` or presence of `~/.codex/sessions/` → **Codex** context
- If running as Claude Code (responding to this prompt), you are always in Claude Code context

---

## Section 2 — Score a Session (native, no CLI)

### Claude Code path

**Session discovery:**
1. Glob `~/.claude/projects/` for project directories (skip `*/subagents/`)
2. In the most recently modified project dir, select the latest `*.jsonl` NOT under `*/subagents/`
3. Hard cap: read at most 500 records; skip early if file is very large

**Record parsing rules:**
- Skip records where `type` is in: `progress`, `system`, `file-history-snapshot`, `queue-operation`
- `user` records → user turns (content may be string or list of blocks; extract text)
- `assistant` records → assistant turns (content blocks: `text`, `tool_use`, `thinking`)

**Completion detection:**
- Last `assistant` record with `message.stop_reason == "end_turn"` → `"complete"`
- Any record with `type == "last-prompt"` → `"complete"`
- Otherwise → `"incomplete"`

### Codex path

**Session discovery:**
1. Read `~/.codex/session_index.jsonl` — parse lines, sort by `updated_at` desc
2. Take most recent entry; resolve session file path from `id` under `~/.codex/sessions/`
3. Fallback: glob `~/.codex/sessions/**/*.jsonl` sorted by mtime if index absent

**Record parsing rules:**
- `response_item` records → messages (access `payload.role` and `payload.content`)
- `event_msg` records → metadata (usage, completion)

**Completion detection:**
- `event_msg` with `payload.type == "task_complete"` → `"complete"`
- Otherwise → `"incomplete"`

### Shared scoring heuristics (both paths)

**Task classification** — scan first user message with this precedence:
1. `code_change` (highest): "implement", "fix", "feature", "bug", "add", "create", "refactor", "build", "write"
2. `docs_only`: "agents.md", "readme", "claude.md", "skill", "config", "update docs"
3. `review`: "review", "analyze", "check", "audit", "look at"
4. `exploration`: "explain", "how does", "what is", "show me"
- Ties: `code_change` wins over `docs_only` wins over `review` wins over `exploration`
- Default if no match: `"unknown"`

**Workflow signals** — scan all assistant content (only meaningful for `code_change` tasks; mark `"n/a"` for others). Check in priority order: (1) `tool_use` block `input` fields (command strings), (2) tool result text, (3) assistant prose as fallback:
- `branch_created`: look for "git checkout -b" or "git switch -c"
- `used_uv`: look for "uv run" or "uv sync"
- `ran_tests`: look for "pytest", "test passed", "tests pass"
- `ran_lint`: look for "ruff check" or "ruff format"
- `created_pr`: look for "gh pr create" or "pull request"

**Friction signals** — scan user turns after the first:
- `user_corrections`: look for "that's wrong", "no,", "actually,", "you missed", "not what I asked"
- `clarification_needed`: look for "what do you mean", "can you clarify", "I don't understand", "which one"
- `execution_errors`: look for tool results with exit code ≠ 0 or text containing "Error:", "Traceback"

**Workflow failures** — derive from workflow signals (only for `code_change`):
- `missing_branch` if `branch_created == false`
- `missing_tests` if `ran_tests == false`
- `missing_lint` if `ran_lint == false`

**Optimization relevance** — scan the entire session for the most prominent steering surface:
- `"agents"` if mentions AGENTS.md, CLAUDE.md, global config
- `"readme"` if mentions README.md as a guidance source
- `"skill"` if mentions skill, SKILL.md
- `"config"` if mentions pyproject.toml, .codex config, agent settings
- `"none"` if none of the above

**Claim synthesis** — produce one claim per detected signal:
- For each `true` workflow signal: type=`"process"`, pass=`true`, severity=`"low"`
- For each `false` workflow signal (code_change only): type=`"process"`, pass=`false`, severity=`"high"`
- For each friction signal: type=`"behavioral"`, pass=`false`, severity=`"medium"`

**Score output schema** (produce this exact JSON structure):
```json
{
  "task": "<first user message, truncated to 200 chars>",
  "task_type": "code_change|docs_only|review|exploration|unknown",
  "outcome": "complete|incomplete|unknown",
  "workflow_signal_breakdown": {
    "branch_created": true|false|"n/a",
    "used_uv": true|false|"n/a",
    "ran_tests": true|false|"n/a",
    "ran_lint": true|false|"n/a",
    "created_pr": true|false|"n/a"
  },
  "friction_signals": ["user_corrections", "execution_errors"],
  "workflow_failures": ["missing_branch", "missing_tests"],
  "optimization_relevance": "agents|readme|skill|config|none",
  "claims": [
    {
      "type": "process|behavioral|efficiency|correctness",
      "claim": "<assertion text>",
      "evidence": "<turn excerpt or signal name>",
      "pass": true|false,
      "severity": "high|medium|low"
    }
  ]
}
```

After producing the JSON, provide a brief human-readable summary (3-5 sentences): task description, outcome, top workflow gaps, and the primary optimization surface.

---

## Section 3 — One-Shot Traced Run

Run a single agent task and score the result.

### Claude Code path

```bash
env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS \
  claude -p "<task prompt>" --output-format json
```

Parse result:
- If stdout is a JSON object: check `type == "result"`, fail fast if `is_error == true`, extract `result` string
- If stdout is a JSON array: find element with `type == "result"`, apply same checks

After capturing output, apply Section 2 heuristics to the output text and produce the score schema.

### Codex path

```bash
codex exec --json --skip-git-repo-check "<task prompt>"
```

Parse JSONL stdout line by line:
- Find event with `type == "item.completed"` where `item.type == "agent_message"` — extract response text from `item.content`
- Find event with `type == "turn.completed"` to confirm finish

After capturing output, apply Section 2 heuristics and produce the score schema.

---

## Section 4 — A/B Eval

Compare two variants (e.g. two AGENTS.md versions, two config options) on a task.

1. Accept two variant descriptions from the user
2. For each variant:
   - Apply the variant change to a temp copy or describe it in the prompt context
   - Run Section 3 one-shot with the same task prompt
   - Produce a Section 2 score for each run
3. Feed both outputs and scores to `agents/comparator.md` workflow
4. Report: winner, rubric scores (instruction adherence, completeness, efficiency, correctness), reasoning

---

## Section 5 — Subagent Workflows

These standalone templates work without any CLI install:

| Agent | File | When to use |
|-------|------|-------------|
| Behavioral Grader | `agents/grader.md` | Grade session against behavioral expectations. Accepts raw session JSONL path or pre-scored JSON. Writes `grading.json`. |
| A/B Comparator | `agents/comparator.md` | Blind qualitative comparison of two outputs. Writes `comparison.json`. |
| Pattern Analyzer | `agents/analyzer.md` | Find patterns across multiple sessions. Accepts raw JSONL files or pre-scored JSONs. Writes `analysis.json`. |

Invoke by telling your agent: "Read `agents/grader.md` and follow those instructions with these expectations: [...]"

---

## Section 6 — Agentkaizen CLI (Optional / CI)

For reproducible batch runs, multi-run dispersion stats, W&B Weave integration:

```bash
uv tool install "git+https://github.com/TheIllusionOfLife/AgentKaizen"
agentkaizen --help
```

All `uv run agentkaizen ...` commands become `agentkaizen ...` after install.

For development (editing the repo):
```bash
git clone https://github.com/TheIllusionOfLife/AgentKaizen
cd AgentKaizen && uv sync --group dev
uv run agentkaizen --help
```
