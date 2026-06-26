from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, UploadFile, File, Form, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid, asyncio, os, glob
from concurrent.futures import ThreadPoolExecutor
from langgraph.types import Command
from graph import pipeline
from auth import create_token, verify_token, ADMIN_USERNAME, ADMIN_PASSWORD
from run_store import create_run, update_run, get_runs, get_run

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

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
    if body.username != ADMIN_USERNAME or body.password != ADMIN_PASSWORD:
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


# ── PIPELINE (unchanged from your version) ────────────────────────────────────

async def safe_send(task_id: str, event: str, data: dict):
    ws = active_connections.get(task_id)
    if ws:
        try:
            await ws.send_json({"event": event, **data})
        except Exception:
            pass


def _collect_stream(input_data, config: dict) -> tuple[list, bool, dict]:
    """Run LangGraph stream to completion. Never break early — that raises GeneratorExit."""
    results = []
    interrupted = False
    for chunk in pipeline.stream(input_data, config=config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            interrupted = True
            continue
        node_name = next(iter(chunk))
        results.append((node_name, chunk[node_name]))
    snapshot = pipeline.get_state(config)
    return results, interrupted, snapshot.values


async def run_pipeline(task_id: str, initial_state: dict):
    config = {"configurable": {"thread_id": task_id}}
    loop = asyncio.get_event_loop()

    try:
        results, interrupted, state = await loop.run_in_executor(
            executor, _collect_stream, initial_state, config
        )

        for node_name, node_output in results:
            await safe_send(task_id, "node_complete", {
                "node": node_name,
                "state": node_output
            })

        if interrupted:
            await safe_send(task_id, "hitl_required", {
                "node": results[-1][0] if results else "hitl",
                "stage": state.get("current_stage", ""),
                "payload": state,
            })
            update_run(task_id, status="waiting", outcome=state.get("current_stage"))
        elif state.get("error"):
            await safe_send(task_id, "error", {"message": state["error"]})
            update_run(task_id, status="error", error=state["error"])
        else:
            await safe_send(task_id, "pipeline_complete", {
                "message": "Pipeline finished successfully"
            })
            update_run(task_id, status="complete", outcome="done")

    except Exception as e:
        await safe_send(task_id, "error", {"message": str(e)})
        update_run(task_id, status="error", error=str(e))


async def run_pipeline_resume(task_id: str, decision: dict):
    config = {"configurable": {"thread_id": task_id}}
    loop = asyncio.get_event_loop()

    resume_value = {
        "action": decision["action"],
        "feedback": decision.get("feedback", ""),
    }
    if "edited_code" in decision:
        resume_value["edited_code"] = decision["edited_code"]

    try:
        results, interrupted, state = await loop.run_in_executor(
            executor, _collect_stream, Command(resume=resume_value), config
        )

        for node_name, node_output in results:
            await safe_send(task_id, "node_complete", {
                "node": node_name,
                "state": node_output
            })

        if interrupted:
            await safe_send(task_id, "hitl_required", {
                "node": results[-1][0] if results else "hitl",
                "stage": state.get("current_stage", ""),
                "payload": state,
            })
            update_run(
                task_id,
                status="waiting",
                outcome=state.get("current_stage"),
                **({"pr_url": state["pr_url"]} if state.get("pr_url") else {})
            )
        elif state.get("error"):
            await safe_send(task_id, "error", {"message": state["error"]})
            update_run(task_id, status="error", error=state["error"])
        else:
            await safe_send(task_id, "pipeline_complete", {
                "message": "Pipeline finished successfully"
            })
            update_run(
                task_id,
                status="complete",
                outcome="done",
                **({"pr_url": state["pr_url"]} if state.get("pr_url") else {})
            )

    except Exception as e:
        await safe_send(task_id, "error", {"message": str(e)})
        update_run(task_id, status="error", error=str(e))


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.post("/api/run")
async def start_run(
        instructions: str = Form(...),
        files: list[UploadFile] = File(default=[]),
        username: str = Depends(verify_token)
):
    task_id = str(uuid.uuid4())

    doc_contents = []
    file_names = []
    for f in files:
        content = await f.read()
        doc_contents.append(content.decode("utf-8", errors="ignore"))
        file_names.append(f.filename)

    initial_state = {
        "task_id": task_id,
        "raw_instructions": instructions,
        "uploaded_docs": doc_contents,
        "clarified_spec": instructions + (
            "\n\n" + "\n".join(doc_contents) if doc_contents else ""
        ),
        "arch_context": "",
        "generated_code": {},
        "review_comments": [],
        "test_results": {},
        "pr_url": None,
        "deploy_status": None,
        "hitl_decisions": {},
        "hitl_feedback": {},
        "current_stage": "starting",
        "error": None
    }

    create_run(task_id, instructions, file_names)
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