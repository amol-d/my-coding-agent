# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this project is

An **agentic SDLC platform**: a human-in-the-loop (HITL) "coding agent" that takes a
natural-language task, generates code changes against a **local target repository**,
reviews and tests them, and opens a GitHub pull request — pausing for human approval at
each stage.

It is a FastAPI backend orchestrating a **LangGraph** state machine of specialized LLM
agents, plus a React/Vite frontend for driving runs and approving checkpoints.

> Note: this repo *is* the agent. The code it edits lives in a **separate** repo pointed
> to by `LOCAL_REPO_PATH` (see Configuration). Do not confuse the two — the agents' file
> and git operations in `tools/local_repo.py` all act on `LOCAL_REPO_PATH`, not on this repo.

## Architecture

### Pipeline (LangGraph)

Defined in [`graph.py`](graph.py). State flows through nodes; `MemorySaver` checkpoints
each `thread_id` (= `task_id`) so runs can pause at HITL interrupts and resume.

```
ingest → plan → hitl_plan ─approved→ coding → review → hitl_code ─approved→ testing → hitl_tests
              (revise↩)                 ↑ (reject↩)                            │
                                                                    approved/override
                                                                              ↓
   commit ← hitl_commit ←──────────────────────────────────────────────────┘
     │  (approved; git commit, NEVER push)
     ├─ options.create_pr → pr_manager ─┐
     ├─ options.deploy → hitl_deploy → deploy → END
     └─ else → END
```

- **`ingest`** ([`agents/ingest.py`](agents/ingest.py)) — consolidates raw instructions +
  parsed docs/design-image descriptions + Figma links + RAG arch context into one
  `clarified_spec`.
- **`plan`** ([`agents/planning.py`](agents/planning.py)) — produces an
  `implementation_plan` for human review; incorporates feedback on `revise`.
- **`coding`** ([`agents/coding.py`](agents/coding.py)) — creates/reuses feature branch
  `agent/<task_id[:8]>`, reads existing repo files, asks the LLM for full file contents
  (JSON map of path → content), writes them, records `original_code` for diffing. Retries
  are feedback-aware and bounded by `MAX_CODE_RETRIES`.
- **`review`** ([`agents/review.py`](agents/review.py)) — runs linters (`ruff` / `eslint`),
  then LLM structured review comments (`{file, line, severity, comment}`).
- **`testing`** ([`agents/testing.py`](agents/testing.py)) — generates unit tests, writes
  them, detects the runner (pytest / `npm test`), runs the suite.
- **`commit`** ([`agents/commit.py`](agents/commit.py)) — `git add` + `git commit` only.
  **Never pushes.** Records `commit_sha`.
- **`pr_manager`** ([`agents/pr_manager.py`](agents/pr_manager.py)) — *optional*
  (`options.create_pr`): pushes the branch + opens a GitHub PR via PyGithub.
- **`deploy`** ([`agents/deploy.py`](agents/deploy.py)) — *optional* (`options.deploy`):
  runs `DEPLOY_COMMAND` if set, else no-op.
- **HITL checkpoints** ([`hitl/checkpoints.py`](hitl/checkpoints.py)) — `hitl_plan`,
  `hitl_code`, `hitl_tests`, `hitl_commit`, `hitl_deploy` call LangGraph `interrupt()` to
  pause for a human decision (`approved` / `rejected` / `edit` / `override` / `abort`).
  The frontend keys checkpoints off the interrupt **node name** (`event.node`), not
  `current_stage` (which collides across gates).

### Supporting modules

- [`main.py`](main.py) — FastAPI app: auth, run-history and arch-docs endpoints, the
  `/api/run` (accepts `options` + `figma_links` + files parsed via `doc_ingest`) +
  `/api/resume/{task_id}` routes, and a `/ws/{task_id}` WebSocket. The LangGraph stream
  runs in a `ThreadPoolExecutor`; a concurrent async loop drains the [`events.py`](events.py)
  queue so `stage_started` / `stage_progress` / `node_complete` / `hitl_required` /
  `pipeline_complete` / `error` events reach the UI **live** during the run.
- [`events.py`](events.py) — per-`task_id` event bus (`emit`) + `StepCallbackHandler` that
  surfaces "LLM thinking…" progress. Nodes emit through this since they run off-thread.
- [`llm.py`](llm.py) — OpenAI model factory (`get_llm` / `get_vision_llm`), configurable via
  `OPENAI_MODEL` / `OPENAI_VISION_MODEL`, wires the progress callback.
- [`tools/doc_ingest.py`](tools/doc_ingest.py) — `parse_document` for PDF (`pypdf`), DOCX
  (`python-docx`), design images (vision model), and text/markdown/code.
- [`tools/local_repo.py`](tools/local_repo.py) — all filesystem + git operations against
  `LOCAL_REPO_PATH`. **This is the only module that should touch the target repo.**
  Push lives only in `pr_manager`; the `commit` node never pushes.
- [`arch_rag/`](arch_rag/) — RAG over `./arch_docs/*.md`. `ingest.py` chunks and embeds
  into a persistent Chroma store (`./chroma_db`); `retriever.py` does similarity search.
- [`auth.py`](auth.py) — JWT bearer auth with a single admin user from env vars.
- [`run_store.py`](run_store.py) — run history persisted to `./run_history.json`.
- [`frontend/`](frontend/) — React 19 + Vite + react-router. Pages: Login, TaskIntake,
  Dashboard (live run view + HITL panel), RunHistory, ArchDocs. API client in
  [`frontend/src/api/client.ts`](frontend/src/api/client.ts) targets `http://localhost:8000`.

## Running the project

Backend (Python ≥ 3.12, managed with Poetry):

```bash
poetry install
# one-time: embed architecture docs into the vector store
python -c "from arch_rag.ingest import ingest_arch_docs; ingest_arch_docs()"
uvicorn main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install   # first time only
npm run dev
```

## Configuration (`.env`)

Loaded via `python-dotenv` (`load_dotenv()` is called at the top of most modules). The
`.env` file is git-ignored. Required / notable keys:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | LLM and OpenAI embeddings for RAG |
| `OPENAI_MODEL` | Chat model for agents (default `gpt-4o`) |
| `OPENAI_VISION_MODEL` | Vision model for design screenshots (default `gpt-4o`) |
| `LOCAL_REPO_PATH` | **Absolute path to the target repo the agent edits** |
| `DEFAULT_BRANCH` | Base branch in the target repo for new branches / PRs |
| `DEPLOY_COMMAND` | Optional shell command run by the deploy node (else no-op) |
| `GITHUB_TOKEN` | PAT with `repo` scope, used to open PRs |
| `GITHUB_REPO` | `owner/repo` of the target repo on GitHub |
| `JWT_SECRET` | Signing secret for auth tokens |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | The single login credential pair |
| `LANGSMITH_*` | Optional LangSmith tracing |

⚠️ The local `.env` currently contains **real-looking API keys and tokens**. Never print,
commit, or paste its contents. Treat all secrets as live and rotate anything that leaks.

## Conventions & gotchas

- **Target-repo isolation**: route every file/git action through `tools/local_repo.py`.
  It skips `IGNORE_DIRS`/`IGNORE_FILES` (node_modules, build, lockfiles, etc.).
- **LLM output parsing**: agents expect the model to return raw JSON. They strip ```` ```json ````
  fences and fall back gracefully on parse failure — preserve this defensive pattern when editing.
- **Never break out of the LangGraph stream early** — see the comment in `_collect_stream`
  in `main.py`; breaking raises `GeneratorExit`. Iterate to completion.
- **File paths from the LLM** are `lstrip("/")`-ed to keep them relative to the repo root.
- **Dead code**: several agent files keep a large **commented-out earlier version** at the
  top (e.g. the GPT-4o / GitHub-API-only variants). The live code is below it. Don't
  resurrect the commented blocks without reason.
- **Duplicate `should_retry_code`** in `graph.py`: the second definition (error-aware) wins
  and is the effective one.
- **HITL nodes call `interrupt()` themselves**, so the graph is compiled *without*
  `interrupt_before` — adding it would pause twice.
- **State shape** is the `PipelineState` TypedDict in `graph.py` (`total=False`); use
  `state.get(...)` with fallbacks since state is partial on resume.

## Tooling

- **Python lint**: `ruff` (declared in `pyproject.toml`; also invoked by the review agent).
- **Tests**: `pytest`.
- **Frontend**: `npm run lint` (ESLint), `npm run build` (`tsc -b && vite build`).

There is currently no repo-level test suite for the agent itself; the `testing` agent runs
tests inside the **target** repo, not this one.
