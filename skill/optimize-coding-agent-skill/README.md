# optimize-coding-agent-skill

An agent skill that measures and proves whether your AI coding agent actually follows
instructions — branching discipline, test runs, tool efficiency, and more.

Supports **Claude Code** and **Codex** only.

## Install

```bash
npx skills add TheIllusionOfLife/optimize-coding-agent-skill
```

That's it. The skill is picked up automatically on the next session.

## What It Does

Most AI coding agents _say_ they follow your instructions. This skill gives your agent the
tools to _prove_ it — by tracing runs, scoring sessions against behavioral expectations, and
comparing the before/after impact of any change to your `AGENTS.md`, skill, or config.

The core loop:

```
steer (AGENTS.md / skill / config)
  → trace (record what the agent actually did)
    → score (did it branch? run tests? stay within tool limits?)
      → eval (did the change help vs. baseline?)
        → promote (update the winning steering surface)
```

## Capabilities

### Trace a run

Record exactly what your agent did on a prompt — tool calls, output, token usage, guardrail results:

```
Ask your agent: "Run agentkaizen: trace this prompt — <your task>"
```

Traces are saved to `~/.agentkaizen/traces.jsonl`.

### Score a session

Grade a real interactive session against behavioral expectations:

```
Ask your agent: "Score my last session with agentkaizen"
```

Output includes: task outcome, friction signals, workflow gaps (missing branch, skipped tests),
and **Evidence-Based Claims** — structured pass/fail assertions grouped by type (process,
behavioral, efficiency).

### Compare variants (A/B eval)

Test whether a change to `AGENTS.md` or config actually improved agent behavior:

```
Ask your agent: "Run agentkaizen eval on these two variants"
```

Reports quality score, delta vs. baseline, gate pass/fail, and a blind A/B comparator verdict.
Multi-run mode (`--runs N`) adds mean ± stddev so you don't promote on a lucky single run.

### Generate eval cases

Turn real traces into regression test cases:

```
Ask your agent: "Generate eval cases from recent agentkaizen traces"
```

## Standalone Agent Templates

These templates work without the CLI — just point your agent at the file.

| Template | When to use |
|----------|-------------|
| [`agents/grader.md`](./agents/grader.md) | Grade a session against behavioral assertions (branching, test runs, tool limits). Input: score JSON from `session score --json`. Writes `grading.json`. |
| [`agents/comparator.md`](./agents/comparator.md) | Blind A/B comparison of two agent outputs. No CLI needed. Writes `comparison.json`. |
| [`agents/analyzer.md`](./agents/analyzer.md) | Find patterns across many session scores. Writes `analysis.json`. |

Invoke by telling your agent:

```
"Read agents/grader.md and grade this session against these expectations: [...]"
```

## Setup Check

Verify the underlying CLI is installed and reachable:

```bash
python scripts/check_setup.py
```

Exits 0 on success. Prints fix instructions per failure. Run from the
[AgentKaizen](https://github.com/TheIllusionOfLife/AgentKaizen) repo root.

If AgentKaizen is not installed:

```bash
git clone https://github.com/TheIllusionOfLife/AgentKaizen
cd AgentKaizen && uv sync --group dev
```

## Requirements

- **Agent**: Codex CLI (`codex`) or Claude Code CLI (`claude`)
- **AgentKaizen CLI**: [github.com/TheIllusionOfLife/AgentKaizen](https://github.com/TheIllusionOfLife/AgentKaizen) — install with `uv sync --group dev`
- **W&B Weave**: optional — all workflows run locally without it

## Source

Skill content is maintained in the
[AgentKaizen](https://github.com/TheIllusionOfLife/AgentKaizen) repository under
[`skill/agentkaizen/`](https://github.com/TheIllusionOfLife/AgentKaizen/tree/main/skill/agentkaizen).
File a bug or contribute there.

## License

Apache
