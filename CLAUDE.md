# CLAUDE.md

This file guides Claude Code (and other AI agents) when working in this repository.

The full engineering guide lives in [AGENTS.md](AGENTS.md) — **read it first**. It covers
the architecture, the LangGraph pipeline, how to run the app, configuration, and the
project's conventions and gotchas. This file only adds a short orientation and the rules
most worth repeating.

## TL;DR

This repo is a human-in-the-loop **coding agent**: a FastAPI + LangGraph backend that turns
a natural-language task into reviewed, tested code changes and a GitHub PR against a
**separate target repository**, with a React/Vite frontend for driving runs and approving
each stage.

Pipeline: `coding → review → hitl_code → testing → hitl_tests → pr_manager → hitl_deploy`
(see [`graph.py`](graph.py)).

## Quick start

```bash
# Backend
poetry install
python -c "from arch_rag.ingest import ingest_arch_docs; ingest_arch_docs()"  # one-time RAG index
uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

## Rules that matter most

- **This repo ≠ the code being edited.** The agents modify the repo at `LOCAL_REPO_PATH`,
  not this one. All file/git operations must go through [`tools/local_repo.py`](tools/local_repo.py).
- **Secrets**: `.env` holds live-looking API keys/tokens and is git-ignored. Never print,
  commit, or echo its contents.
- **Don't break the LangGraph stream early** (`GeneratorExit`); run it to completion — see
  `_collect_stream` in [`main.py`](main.py).
- **Preserve the defensive LLM-JSON parsing** in the agents (fence-stripping + fallback).
- **Ignore the large commented-out legacy blocks** at the top of the agent files; the live
  implementation is below them.
- **Match existing style** in whatever file you touch; keep changes minimal and scoped.

For anything beyond this, defer to [AGENTS.md](AGENTS.md).
