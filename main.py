from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, WebSocket, UploadFile, File, Form, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uuid, asyncio
from concurrent.futures import ThreadPoolExecutor
from langgraph.types import Command
from graph import pipeline

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

active_connections: dict[str, WebSocket] = {}
executor = ThreadPoolExecutor(max_workers=4)


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
        elif state.get("error"):
            await safe_send(task_id, "error", {"message": state["error"]})
        else:
            await safe_send(task_id, "pipeline_complete", {
                "message": "Pipeline finished successfully"
            })

    except Exception as e:
        await safe_send(task_id, "error", {"message": str(e)})


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
        elif state.get("error"):
            await safe_send(task_id, "error", {"message": state["error"]})
        else:
            await safe_send(task_id, "pipeline_complete", {
                "message": "Pipeline finished successfully"
            })

    except Exception as e:
        await safe_send(task_id, "error", {"message": str(e)})


@app.post("/api/run")
async def start_run(
        instructions: str = Form(...),
        files: list[UploadFile] = File(default=[])
):
    task_id = str(uuid.uuid4())

    doc_contents = []
    for f in files:
        content = await f.read()
        doc_contents.append(content.decode("utf-8", errors="ignore"))

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

    asyncio.create_task(run_pipeline(task_id, initial_state))
    return {"task_id": task_id}


@app.post("/api/resume/{task_id}")
async def resume_run(task_id: str, decision: dict):
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
