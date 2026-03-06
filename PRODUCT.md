# Product Overview

## Purpose
AgentKaizen helps teams improve CLI-based AI coding agents with measurable experiments instead of trial-and-error edits.

The core problem is steerability. Users can influence agents through many surfaces, such as `AGENTS.md`, repository docs, skills, and tool configuration, but they often lack a reliable way to measure which changes actually improve behavior. AgentKaizen connects those steering inputs to W&B Weave traces and evaluations.

## Target Users
- Advanced users of Codex or similar CLI-based coding agents
- Teams maintaining project-specific agent instructions
- Developers experimenting with prompt and document steering
- Researchers or operators who want reproducible eval loops for agent behavior

## User Jobs
Users come here to:
- trace real Codex runs
- understand failures and friction in interactive sessions
- turn real tasks into regression cases
- compare baseline behavior against candidate instruction or document changes
- promote only the changes that improve results without unacceptable regressions

## Core Features
- Traced `codex exec` runs with guardrail scoring
- Interactive Codex session ingestion and scoring
- Offline evals for document, skill, and config variants
- Draft case generation from recent traces
- Ranking that considers quality, latency, and token usage

## Business and Product Goals
- Make agent steering changes observable
- Reduce guesswork in instruction tuning
- Preserve wins by converting real usage into eval cases
- Help users evolve agent instructions safely over time

## Non-Goals
- Replacing Codex itself
- Building a general-purpose agent framework
- Managing every possible LLM integration
- Providing a hosted UI beyond what W&B Weave already offers

## Product Principles
- Measure changes, do not guess
- Optimize for repeatability and comparability
- Favor small, attributable steering changes over large ambiguous rewrites
- Treat docs and instructions as product surfaces, not just prose
