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

Defined in [`graph.py`](graph.py). State flows through nodes; a **persistent
`SqliteSaver`** checkpoints each `thread_id` (= `task_id`) so runs can pause at HITL
interrupts and resume — and, because the store is a file (`checkpoints.sqlite`, override
with `CHECKPOINT_DB_PATH`), **a paused run survives a backend restart or crash** and can
still be resumed. The connection is opened with `check_same_thread=False` since the graph
is streamed from a `ThreadPoolExecutor`.

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

- **`ingest`** ([`agents/ingest.py`](agents/ingest.py)) — first **classifies intent** from
  the instructions (`code_change` / `git_ops` / `mixed`) and extracts control directives
  (`create_pr`, `deploy`, `create_new_branch`) that override the UI toggles. Pure
  `git_ops` requests (e.g. "push the current branch and open a PR") skip code generation
  and route straight to a confirmation gate + `pr_manager`. Otherwise it consolidates raw
  instructions + parsed docs/design-image descriptions + Figma links + the target repo's
  `AGENTS.md`/`CLAUDE.md` guidance (see `arch_rag`)
  into one `clarified_spec`.
- **`hitl_git_ops`** ([`hitl/checkpoints.py`](hitl/checkpoints.py)) — confirmation gate for
  the git-ops fast path before any push/PR.
- **`plan`** ([`agents/planning.py`](agents/planning.py)) — produces a **structured
  plan** (`state["plan"]`: `summary`, `approach`, `files_to_touch`, **`acceptance_criteria`**,
  `test_strategy`, `risks`) and renders it to the human-readable `implementation_plan`
  markdown for the gate/PR. The **acceptance criteria are load-bearing**: they're injected
  into the coding prompt (build to satisfy them) and the review prompt (any *unmet*
  criterion becomes a `blocking` comment, which the reflect loop auto-fixes). Incorporates
  human feedback on `revise`.
- **`coding`** ([`agents/coding.py`](agents/coding.py)) — an **agentic tool-use loop**
  (not a single-shot generation). It creates/reuses feature branch `agent/<task_id[:8]>`
  (or the current branch when `create_new_branch` is false), then lets the model iterate
  with a small tool set — `list_files` / `read_file` / `grep` (explore),
  `create_file` / `apply_patch` (edit), `run_command` (verify) — until it calls `finish`
  or hits `MAX_AGENT_STEPS`. Edits are **targeted search/replace patches**
  ([`tools/patch.py`](tools/patch.py)) whose `find` must match exactly once, so large
  files aren't rewritten or truncated. Tools are built per run by
  [`tools/agent_tools.py`](tools/agent_tools.py); a `Tracker` records each touched file's
  pre-edit content so the node still returns `generated_code` (path → final content) and
  `original_code` for diffing — an **unchanged contract**, so `review` / `testing` / HITL
  gates are unaffected. `run_command` ([`tools/sandbox.py`](tools/sandbox.py)) has **two
  isolation tiers**: a per-command **Docker container** (worktree mounted at `/work`,
  `--network none`, `--cap-drop ALL`, `no-new-privileges`, memory/cpu/pids limits,
  non-root, `--rm`) when Docker is usable, else an **allowlisted, no-shell host
  subprocess**. `SANDBOX_DOCKER` = `auto` (default) / `on` (require Docker) / `off`
  (always host); the allowlist (build/test/lint/read-only-git only, no metacharacters) is
  enforced in both tiers. Retries stay feedback-aware and bounded by `MAX_CODE_RETRIES`.
- **`review`** ([`agents/review.py`](agents/review.py)) — runs linters (`ruff` / `eslint`),
  then LLM structured review comments (`{file, line, severity, comment}`). If any are
  `blocking`, `route_after_review` loops **back to `coding` to self-fix** (bounded by
  `MAX_CODE_RETRIES`) *before* the human gate; otherwise it goes to `hitl_code`.
- **`testing`** ([`agents/testing.py`](agents/testing.py)) — generates unit tests, writes
  them, detects the runner (pytest / `npm test`), runs the suite. On a real failure
  (`status == "failed"`, not skipped / no-runner) `route_after_testing` loops **back to
  `coding`** with the failure output (bounded) before `hitl_tests`.
- **Reflect loop** — the coding node assembles `_reflection_notes` (human rejection
  feedback + blocking review comments + test-failure output) into its prompt, so a retry
  addresses the concrete signals and verifies with `run_command`. Auto-reflection, human
  rejections, and the coding loop all re-enter `coding` and **share the `MAX_CODE_RETRIES`
  budget**, so the pipeline converges or escalates to a human rather than spinning.
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
  surfaces "LLM thinking…" progress **and captures token usage** on every response, feeding
  [`usage.py`](usage.py) and emitting live `usage` events (running tokens + cost) to the UI.
  Nodes emit through this since they run off-thread.
- [`usage.py`](usage.py) — per-run **token + cost accounting** (thread-safe; totals persist
  across HITL pauses, reset when the run ends). Cost comes from a model-prefix price table
  (override the fallback with `OPENAI_PRICE_IN`/`OPENAI_PRICE_OUT`). `over_budget()` backs a
  **soft budget guard** (`RUN_BUDGET_USD`) that stops the coding loop once a run's cost hits
  the cap. Totals are persisted to `run_store` (`cost_usd`, `tokens_total`, `llm_calls`).
- [`llm.py`](llm.py) — OpenAI model factory (`get_llm` / `get_vision_llm`), configurable via
  `OPENAI_MODEL` / `OPENAI_VISION_MODEL`, wires the progress + usage callback (with the
  resolved model name for pricing) and per-request `timeout` / `max_retries`.
- [`tools/doc_ingest.py`](tools/doc_ingest.py) — `parse_document` for PDF (`pypdf`), DOCX
  (`python-docx`), design images (vision model), and text/markdown/code.
- [`tools/local_repo.py`](tools/local_repo.py) — all filesystem + git operations against
  `LOCAL_REPO_PATH`. **This is the only module that should touch the target repo.**
  Push lives only in `pr_manager`; the `commit` node never pushes.
  - **Per-run worktree isolation:** each code-change run operates in its own **git
    worktree** (`create_worktree` / `remove_worktree`, under `WORKTREE_BASE`) on a fresh
    branch, so concurrent runs don't collide and a failed/aborted run is discarded without
    ever dirtying the main checkout. Which repo a call targets is a `ContextVar`
    (`set_active_repo` / `active_root`) that each repo-touching node sets from
    `state["worktree_path"]` at entry — so it stays correct across HITL resume and the
    4-worker executor. `git_ops` and `create_new_branch=false` requests intentionally stay
    on the main checkout (a worktree can't check out an already-checked-out branch).
    Worktree commits land in the shared object DB, so the branch + commits **persist in the
    main repo after the worktree is removed** (`_cleanup_worktree` in `main.py`, called only
    on terminal states — never on a HITL pause).
- [`arch_rag/`](arch_rag/) — convention/architecture context for the agents.
  `retriever.get_arch_context` sources it **primarily from the target repo's own
  `AGENTS.md` / `CLAUDE.md`** (root or under `.claude/`; `get_repo_guidelines`, read via
  `tools/local_repo`, so it's always current for that repo — the same way Codex / Claude
  Code work; identical content found in two locations is de-duplicated). It falls back to
  **semantic retrieval over `./arch_docs/*.md`** (Chroma; built one-time by `ingest.py`) only
  when the target repo has no guidance files, so a large external corpus is still supported
  but never required. Chroma/embeddings are imported lazily, so the common path pulls in
  neither.
- [`auth.py`](auth.py) — JWT bearer auth with a single admin user from env vars.
  Credentials are checked in constant time (`verify_credentials`); `decode_token` is a
  non-raising validator used for the WebSocket handshake (which authenticates via a
  `?token=` query param since browsers can't set Authorization on a WS). `security_warnings`
  is printed at startup if the insecure default `JWT_SECRET`/`ADMIN_PASSWORD` are in use.
  CORS is restricted to `ALLOWED_ORIGINS`.
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
| `OPENAI_TIMEOUT` | Per-request timeout in seconds (default `90`) |
| `OPENAI_MAX_RETRIES` | Retries with exponential backoff on transient LLM failures (default `5`) |
| `MAX_CODE_RETRIES` | Shared budget for auto-reflection + human-rejection coding retries (default `3`) |
| `RUN_BUDGET_USD` | Soft per-run cost cap; stops the coding loop when reached (`0` = disabled) |
| `OPENAI_PRICE_IN` / `OPENAI_PRICE_OUT` | Fallback USD-per-1K-token price for unknown models |
| `SANDBOX_DOCKER` | Command sandbox: `auto` (Docker if usable, else host) / `on` / `off` (default `auto`) |
| `SANDBOX_IMAGE` | Docker image for sandboxed commands (default `python:3.12-slim`; use a node-capable image for JS/TS repos) |
| `SANDBOX_NETWORK` | Container network (`none` default / `bridge` / `host`); `SANDBOX_MEMORY`/`SANDBOX_CPUS`/`SANDBOX_PIDS` cap resources |
| `LOCAL_REPO_PATH` | **Absolute path to the target repo the agent edits** |
| `DEFAULT_BRANCH` | Base branch in the target repo for new branches / PRs |
| `DEPLOY_COMMAND` | Optional shell command run by the deploy node (else no-op) |
| `CHECKPOINT_DB_PATH` | SQLite file for the persistent checkpointer (default `checkpoints.sqlite`) |
| `WORKTREE_BASE` | Directory holding per-run git worktrees (default: system-temp `coding-agent-worktrees`) |
| `GITHUB_TOKEN` | PAT with `repo` scope, used to open PRs |
| `GITHUB_REPO` | `owner/repo` of the target repo on GitHub |
| `JWT_SECRET` | Signing secret for auth tokens |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | The single login credential pair |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins for API + WebSocket (default local dev) |
| `LANGSMITH_*` | Optional LangSmith tracing |

⚠️ The local `.env` currently contains **real-looking API keys and tokens**. Never print,
commit, or paste its contents. Treat all secrets as live and rotate anything that leaks.
Copy [`.env.example`](.env.example) to `.env` and fill in real values; the example holds
placeholders only. **Set a strong `JWT_SECRET` and `ADMIN_PASSWORD`** — the defaults are
insecure and the server logs a `[SECURITY]` warning at startup while they're in use.

File paths from LLM output are confined to the target repo by `_safe_path` in
[`tools/local_repo.py`](tools/local_repo.py): `read_file`/`write_file` reject `../`
traversal (and neutralize leading `/`), so generated code can't touch files outside
`LOCAL_REPO_PATH`.

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
- **Tests**: `pytest` (config in `pyproject.toml` → `[tool.pytest.ini_options]`).
- **Frontend**: `npm run lint` (ESLint), `npm run build` (`tsc -b && vite build`).

### Agent test suite (`tests/`)

`poetry run pytest` runs the agent's own suite — deterministic, no LLM calls, no network.
It locks in the load-bearing invariants: graph **routing** and the **reflect loop**
(`test_routing.py`, `test_reflection.py`), the **patch** exact-match/atomicity guard
(`test_patch.py`), the **sandbox** allowlist + hardened docker argv + mode fallback
(`test_sandbox.py`), per-run **worktree** isolation/persistence (`test_worktree.py`),
`local_repo` helpers (`test_local_repo.py`), and NL **directive merging** (`test_ingest.py`).
The `repo` fixture in `conftest.py` points `tools.local_repo` at a throwaway git repo, and
`CHECKPOINT_DB_PATH` is redirected to a temp file so importing `graph` doesn't touch the
repo. (This is distinct from the `testing` agent, which runs tests inside the **target**
repo.)
