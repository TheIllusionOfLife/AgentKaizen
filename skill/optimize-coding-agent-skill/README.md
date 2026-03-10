# optimize-coding-agent-skill

An agent skill that measures and proves whether your AI coding agent actually follows instructions — branching discipline, test runs, tool efficiency, and more. **No installation required.**

Supports **Claude Code** and **Codex** only.

## Install

```bash
npx skills add TheIllusionOfLife/optimize-coding-agent-skill
```

That's it. Invoke the skill in your next session.

## Usage

**Claude Code:**
```
/optimize-coding-agent score my last session
/optimize-coding-agent trace: write a hello world function
/optimize-coding-agent compare these two AGENTS.md variants on this task: [...]
```

**Codex:**
```
$optimize-coding-agent analyze my last session
$optimize-coding-agent run: implement a hello world function
```

The agent handles everything natively — reading session files, running one-shot tasks, and scoring — using only its built-in tools. No Python, no `uv sync`, no `git clone`.

## What It Does

Most AI coding agents _say_ they follow your instructions. This skill gives your agent the tools to _prove_ it — by analyzing sessions, scoring behavior against expectations, and comparing the before/after impact of any change to your `AGENTS.md`, skill, or config.

The core loop:

```
steer (AGENTS.md / skill / config)
  → score (did it branch? run tests? stay within tool limits?)
    → eval (did the change help vs. baseline?)
      → promote (update the winning steering surface)
```

## Capabilities

### Score a session (native — no install needed)

Grade a real interactive session against behavioral expectations. The agent reads your local session files directly:

```
Ask your agent: "Score my last session" or "/optimize-coding-agent score my last session"
```

Output includes: task outcome, friction signals, workflow gaps (missing branch, skipped tests), and structured Evidence-Based Claims — pass/fail assertions grouped by type (process, behavioral, efficiency).

### One-shot traced run

Run a single task and score the result:

```
/optimize-coding-agent trace: write a function that reverses a string
```

### Compare variants (A/B eval)

Test whether a change to `AGENTS.md` or config actually improved agent behavior:

```
/optimize-coding-agent compare: [variant A description] vs [variant B description] on task: [...]
```

Reports quality score, delta vs. baseline, and a blind A/B comparator verdict.

## Standalone Agent Templates

These templates work without any CLI — just point your agent at the file.

| Template | When to use |
|----------|-------------|
| [`optimize-coding-agent-skill/agents/grader.md`](./optimize-coding-agent-skill/agents/grader.md) | Grade a session against behavioral assertions. Accepts raw session JSONL or pre-scored JSON. Writes `grading.json`. |
| [`optimize-coding-agent-skill/agents/comparator.md`](./optimize-coding-agent-skill/agents/comparator.md) | Blind A/B comparison of two agent outputs. Writes `comparison.json`. |
| [`optimize-coding-agent-skill/agents/analyzer.md`](./optimize-coding-agent-skill/agents/analyzer.md) | Find patterns across many sessions. Accepts raw JSONL or pre-scored JSON. Writes `analysis.json`. |

Invoke by telling your agent:

```
"Read optimize-coding-agent-skill/agents/grader.md and grade this session against these expectations: [...]"
```

## Advanced / CI Use

For reproducible batch runs, multi-run dispersion stats, and W&B Weave integration:

```bash
uv tool install "git+https://github.com/TheIllusionOfLife/AgentKaizen"
agentkaizen --help
```

All `agentkaizen` commands (run, eval, session sync/score) work after install. See the [AgentKaizen repo](https://github.com/TheIllusionOfLife/AgentKaizen) for full CLI documentation.

## Requirements

- **Agent**: Codex CLI (`codex`) or Claude Code CLI (`claude`)
- **AgentKaizen CLI**: optional — only needed for batch CI runs, W&B Weave integration, or multi-run dispersion stats

## Source

Skill content is maintained in the
[AgentKaizen](https://github.com/TheIllusionOfLife/AgentKaizen) repository under
[`skill/optimize-coding-agent-skill/`](https://github.com/TheIllusionOfLife/AgentKaizen/tree/main/skill/optimize-coding-agent-skill).
File a bug or contribute there.

## License

Apache
