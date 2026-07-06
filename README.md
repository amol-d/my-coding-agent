# my-coding-agent

A human-in-the-loop (HITL) **coding agent**: give it a natural-language task (optionally
with PRD/BRD/architecture docs or a Figma screenshot) and it plans, writes code, reviews,
tests, and commits reviewed changes to a **separate target repository** — pausing for your
approval at every stage, and optionally opening a GitHub PR.

It's a **FastAPI + LangGraph** backend orchestrating specialized LLM agents, with a
**React/Vite** frontend for driving runs and approving each checkpoint.

> This repo *is* the agent. The code it edits lives in a **separate** repo pointed to by
> `LOCAL_REPO_PATH` — the two are never the same.

For the full engineering guide (architecture, conventions, gotchas), see
[AGENTS.md](AGENTS.md).

## Pipeline

```
ingest → plan → hitl_plan ─approved→ coding → review → hitl_code → testing → hitl_tests
   │  (classify intent,     (structured plan   │  (agentic tool loop,   │        │
   │   consolidate docs)     + acceptance       │   patch editing)   auto-reflect on
   │                         criteria)          └── auto-reflect on   failing tests
   │                                                 blocking review        │
   ├─ git-ops fast path → hitl_git_ops → pr_manager        ↓                ↓
   │  ("push branch / open PR")                    hitl_commit → commit (never pushes)
   └─ … then optional: pr_manager (push + PR) · hitl_deploy → deploy
```

Every `hitl_*` node pauses for a human decision (approve / reject / edit / abort).

## Highlights

- **Agentic coding loop** — the model works with tools (`list_files` / `grep` / `read_file`,
  `create_file` / `apply_patch`, `run_command`) and iterates until done. Edits are targeted
  **search/replace patches** (no whole-file rewrites), so large files aren't truncated.
- **Per-run isolation** — each run operates in its own **git worktree** on a fresh branch, so
  concurrent runs never collide and a failed run is discarded without touching the checkout.
- **Structured plans with acceptance criteria** that drive the loop: coding builds to satisfy
  them, review flags any unmet criterion as *blocking*.
- **Closed reflect loop** — blocking review comments and failing tests route back to coding
  for a bounded self-fix before the human is asked.
- **Command sandbox** — commands run in a per-run **Docker container** (no network, dropped
  caps, resource limits) when available, else an allowlisted host subprocess.
- **Durable runs** — a SQLite checkpointer means a paused run survives a backend restart and
  can still be resumed.
- **Resilience & cost control** — per-request timeouts + retry/backoff on LLM calls, plus live
  **token/cost tracking** with an optional per-run budget cap.
- **Intent-driven git** — natural-language directives ("push the current branch and open a PR
  to dev") drive pushes/PRs directly, overriding the UI toggles.
- **Convention-aware** — reads the target repo's own `AGENTS.md` / `CLAUDE.md` for
  architecture context (falling back to optional RAG over `arch_docs/` for a large external
  corpus), plus PRD/BRD as PDF/DOCX and Figma **screenshots** interpreted by a vision model.
- **Security** — JWT auth (API + WebSocket), constant-time credentials, and a path-traversal
  guard confining all file writes to the target repo.

## Quick start

Requires Python ≥ 3.12 (with [Poetry](https://python-poetry.org/)) and Node.js.

```bash
# 1. Configure
cp .env.example .env            # then edit: set OPENAI_API_KEY, LOCAL_REPO_PATH,
                                # DEFAULT_BRANCH, a strong JWT_SECRET + ADMIN_PASSWORD, …

# 2. Backend
poetry install
python -c "from arch_rag.ingest import ingest_arch_docs; ingest_arch_docs()"  # one-time RAG index
poetry run uvicorn main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install                     # first time only
npm run dev
```

Open the frontend (Vite prints the URL, typically http://localhost:5173), log in with your
`ADMIN_USERNAME` / `ADMIN_PASSWORD`, and start a run.

## Configuration

All configuration is via `.env` (git-ignored). Copy [`.env.example`](.env.example) — it
documents every variable, including the target repo (`LOCAL_REPO_PATH`, `DEFAULT_BRANCH`),
the command sandbox (`SANDBOX_DOCKER`, `SANDBOX_IMAGE`, …), the cost budget
(`RUN_BUDGET_USD`), and auth (`JWT_SECRET`, `ALLOWED_ORIGINS`). See the Configuration table
in [AGENTS.md](AGENTS.md) for details.

> ⚠️ Set a strong `JWT_SECRET` and `ADMIN_PASSWORD` — the defaults are insecure and the
> server logs a `[SECURITY]` warning while they're in use. Never commit your real `.env`.

## Testing

```bash
poetry run pytest        # backend: routing, reflect loop, patch guard, sandbox, worktree,
                         # usage/cost, and security invariants (no LLM calls, no network)

cd frontend
npm run lint
npm run build            # tsc + vite build
```

## Tech stack

FastAPI · LangGraph (with SQLite checkpointing) · LangChain + OpenAI (chat + vision) ·
Chroma (optional RAG fallback over `arch_docs/`) · PyGithub · React 19 + Vite + TypeScript.
