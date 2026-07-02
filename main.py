from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, UploadFile, File, Form, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid, asyncio, os, glob, json, queue
from concurrent.futures import ThreadPoolExecutor
from langgraph.types import Command
from graph import pipeline
from auth import (
    create_token, verify_token, decode_token, verify_credentials, security_warnings,
)
from run_store import create_run, update_run, get_runs, get_run
import events
import usage
from tools.doc_ingest import parse_document
from tools.local_repo import remove_worktree, worktree_path_for

app = FastAPI()

# Restrict browser origins to the configured frontend(s); default to local dev.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

for _w in security_warnings():
    print(f"[SECURITY] {_w}")

active_connections: dict[str, WebSocket] = {}
executor = ThreadPoolExecutor(max_workers=4)

ARCH_DOCS_DIR = "./arch_docs"
os.makedirs(ARCH_DOCS_DIR, exist_ok=True)


# ── AUTH ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/api/auth/login")
async def login(body: LoginRequest):
    if not verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(body.username)
    return {"token": token, "username": body.username}

@app.get("/api/auth/me")
async def me(username: str = Depends(verify_token)):
    return {"username": username}


# ── RUN HISTORY ───────────────────────────────────────────────────────────────

@app.get("/api/runs")
async def list_runs(username: str = Depends(verify_token)):
    return {"runs": get_runs()}

@app.get("/api/runs/{task_id}")
async def get_run_detail(task_id: str, username: str = Depends(verify_token)):
    run = get_run(task_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ── ARCH DOCS ─────────────────────────────────────────────────────────────────

@app.get("/api/arch-docs")
async def list_arch_docs(username: str = Depends(verify_token)):
    files = glob.glob(f"{ARCH_DOCS_DIR}/**/*.md", recursive=True)
    result = []
    for path in files:
        stat = os.stat(path)
        result.append({
            "name": os.path.relpath(path, ARCH_DOCS_DIR),
            "size": stat.st_size,
            "modified": stat.st_mtime
        })
    return {"docs": result}

@app.post("/api/arch-docs/upload")
async def upload_arch_docs(
    files: list[UploadFile] = File(...),
    username: str = Depends(verify_token)
):
    saved = []
    for f in files:
        if not f.filename.endswith(".md"):
            continue
        dest = os.path.join(ARCH_DOCS_DIR, f.filename)
        content = await f.read()
        with open(dest, "wb") as out:
            out.write(content)
        saved.append(f.filename)
    return {"saved": saved}

@app.delete("/api/arch-docs/{filename}")
async def delete_arch_doc(filename: str, username: str = Depends(verify_token)):
    path = os.path.join(ARCH_DOCS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    os.remove(path)
    return {"deleted": filename}

@app.post("/api/arch-docs/reindex")
async def reindex_arch_docs(username: str = Depends(verify_token)):
    def _reindex():
        from arch_rag.ingest import ingest_arch_docs
        ingest_arch_docs()
        return True
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, _reindex)
    return {"status": "reindexed"}


# ── PIPELINE ──────────────────────────────────────────────────────────────────

async def _send_raw(task_id: str, payload: dict):
    ws = active_connections.get(task_id)
    if ws:
        try:
            await ws.send_json(payload)
        except Exception:
            pass


async def safe_send(task_id: str, event: str, data: dict):
    await _send_raw(task_id, {"event": event, **data})


async def _drain_events(task_id: str):
    """Forward live events emitted by graph nodes to the WebSocket until the
    sentinel (None) is enqueued. Runs concurrently with the blocking graph stream."""
    q = events.get_queue(task_id)
    while True:
        try:
            item = q.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue
        if item is None:                     # sentinel — stream finished
            break
        await _send_raw(task_id, item)


def _collect_stream(input_data, config: dict) -> tuple[list, bool, dict, str | None]:
    """Run LangGraph stream to completion. Never break early — that raises GeneratorExit.
    Node-level progress is emitted live via events.emit inside the nodes themselves."""
    results = []
    for chunk in pipeline.stream(input_data, config=config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            continue
        node_name = next(iter(chunk))
        results.append((node_name, chunk[node_name]))
    snapshot = pipeline.get_state(config)
    interrupted = bool(snapshot.next)
    interrupt_node = snapshot.next[0] if snapshot.next else None
    return results, interrupted, snapshot.values, interrupt_node


async def _run_graph(task_id: str, input_data):
    """Shared driver for both a fresh run and a resume: streams the graph while
    draining live events, then emits the terminal event."""
    config = {"configurable": {"thread_id": task_id}}
    loop = asyncio.get_event_loop()

    events.get_queue(task_id)                 # ensure queue exists before draining
    drain = asyncio.create_task(_drain_events(task_id))

    try:
        results, interrupted, state, interrupt_node = await loop.run_in_executor(
            executor, _collect_stream, input_data, config
        )
    finally:
        events.close(task_id)                 # flush + stop the drain loop
        await drain
        events.discard(task_id)

    pr_url = state.get("pr_url")
    extra = {"pr_url": pr_url} if pr_url else {}

    # token + cost accounting so far (persists across HITL pauses; reset on terminal)
    u = usage.totals(task_id)["totals"]
    cost = {"cost_usd": round(u["cost_usd"], 4), "tokens_total": u["total"],
            "llm_calls": u["calls"]}

    if interrupted:
        # paused at a HITL gate — keep the worktree so the run can resume into it
        await safe_send(task_id, "hitl_required", {
            "node": interrupt_node or (results[-1][0] if results else "hitl"),
            "stage": state.get("current_stage", ""),
            "payload": state,
        })
        update_run(task_id, status="waiting",
                   outcome=state.get("current_stage"), **extra, **cost)
    elif state.get("error"):
        _cleanup_worktree(state)   # terminal failure — discard the isolated worktree
        await safe_send(task_id, "error", {"message": state["error"]})
        update_run(task_id, status="error", error=state["error"], **extra, **cost)
        usage.reset(task_id)
    else:
        _cleanup_worktree(state)   # done — commits persist on the branch in main
        await safe_send(task_id, "usage", {"summary": True, "run_tokens": u["total"],
                                           "run_cost_usd": cost["cost_usd"],
                                           "run_calls": u["calls"]})
        await safe_send(task_id, "pipeline_complete", {
            "message": "Pipeline finished successfully"
        })
        update_run(task_id, status="complete", outcome="done",
                   commit_sha=state.get("commit_sha"), **extra, **cost)
        usage.reset(task_id)


def _cleanup_worktree(state: dict) -> None:
    """Remove a finished run's isolated worktree. Any commits made in it remain
    reachable via their branch in the main checkout, so this only reclaims the
    working directory — it never discards committed work."""
    path = state.get("worktree_path")
    if path:
        try:
            remove_worktree(path)
        except Exception:
            pass


def _cleanup_worktree_by_task(task_id: str) -> None:
    """Reclaim a run's worktree when the stream raised before returning state
    (so we have no worktree_path). Path is deterministic from task_id; a no-op if
    the run never created one (e.g. a git-ops run on the main checkout)."""
    try:
        remove_worktree(worktree_path_for(task_id))
    except Exception:
        pass


async def run_pipeline(task_id: str, initial_state: dict):
    try:
        await _run_graph(task_id, initial_state)
    except Exception as e:
        _cleanup_worktree_by_task(task_id)   # don't leak a worktree on hard failure
        usage.reset(task_id)
        await safe_send(task_id, "error", {"message": str(e)})
        update_run(task_id, status="error", error=str(e))


async def run_pipeline_resume(task_id: str, decision: dict):
    resume_value = {
        "action": decision["action"],
        "feedback": decision.get("feedback", ""),
    }
    if "edited_code" in decision:
        resume_value["edited_code"] = decision["edited_code"]
    try:
        await _run_graph(task_id, Command(resume=resume_value))
    except Exception as e:
        _cleanup_worktree_by_task(task_id)   # don't leak a worktree on hard failure
        usage.reset(task_id)
        await safe_send(task_id, "error", {"message": str(e)})
        update_run(task_id, status="error", error=str(e))


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.post("/api/run")
async def start_run(
        instructions: str = Form(...),
        files: list[UploadFile] = File(default=[]),
        options: str = Form(default="{}"),
        figma_links: str = Form(default="[]"),
        username: str = Depends(verify_token)
):
    task_id = str(uuid.uuid4())

    try:
        run_options = json.loads(options or "{}")
    except json.JSONDecodeError:
        run_options = {}
    try:
        links = json.loads(figma_links or "[]")
    except json.JSONDecodeError:
        links = []

    # parse each uploaded document (PDF / DOCX / image-via-vision / text)
    design_inputs = []
    file_names = []
    doc_texts = []
    for f in files:
        raw = await f.read()
        kind, text = parse_document(f.filename, raw)
        design_inputs.append({"name": f.filename, "kind": kind, "text": text})
        doc_texts.append(text)
        file_names.append(f.filename)

    initial_state = {
        "task_id": task_id,
        "raw_instructions": instructions,
        "uploaded_docs": doc_texts,
        "design_inputs": design_inputs,
        "figma_links": links,
        "options": {"create_pr": bool(run_options.get("create_pr")),
                    "deploy": bool(run_options.get("deploy"))},
        "clarified_spec": "",
        "implementation_plan": "",
        "arch_context": "",
        "generated_code": {},
        "review_comments": [],
        "test_results": {},
        "commit_sha": None,
        "code_retry_count": 0,
        "pr_url": None,
        "deploy_status": None,
        "hitl_decisions": {},
        "hitl_feedback": {},
        "current_stage": "starting",
        "error": None
    }

    create_run(task_id, instructions, file_names, options=initial_state["options"])
    asyncio.create_task(run_pipeline(task_id, initial_state))
    return {"task_id": task_id}


@app.post("/api/resume/{task_id}")
async def resume_run(
        task_id: str,
        decision: dict,
        username: str = Depends(verify_token)
):
    asyncio.create_task(run_pipeline_resume(task_id, decision))
    return {"status": "resuming"}


@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    # Authenticate the handshake: the run stream carries the spec, generated code
    # and file contents, so it must not be world-readable. Browsers can't set
    # Authorization on a WebSocket, so the token is passed as a query param.
    token = websocket.query_params.get("token")
    if not token or decode_token(token) is None:
        await websocket.close(code=1008)   # policy violation
        return
    await websocket.accept()
    active_connections[task_id] = websocket
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        active_connections.pop(task_id, None)
