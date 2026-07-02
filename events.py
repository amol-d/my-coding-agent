"""Real-time event bus for streaming pipeline progress to the frontend.

Nodes run inside a blocking ThreadPoolExecutor (see main.py), so they cannot
touch the asyncio WebSocket directly. Instead each node pushes lightweight
events onto a per-task thread-safe queue; an async drain loop in main.py reads
them and forwards them over the WebSocket while the graph is still running.
"""

import queue
from typing import Any, Optional

from langchain_core.callbacks import BaseCallbackHandler

import usage

# task_id -> Queue of event dicts. A sentinel None is enqueued to end draining.
_queues: dict[str, "queue.Queue"] = {}

# Human-friendly labels for the pipeline stages, used by the UI stepper.
STAGE_LABELS: dict[str, str] = {
    "ingest": "Ingesting documents",
    "plan": "Planning implementation",
    "hitl_plan": "Awaiting plan approval",
    "coding": "Generating code",
    "review": "Reviewing code",
    "hitl_code": "Awaiting code approval",
    "testing": "Writing & running tests",
    "hitl_tests": "Awaiting test approval",
    "hitl_commit": "Awaiting commit approval",
    "commit": "Committing changes",
    "pr_manager": "Creating pull request",
    "hitl_deploy": "Awaiting deploy approval",
    "deploy": "Deploying",
}


def get_queue(task_id: str) -> "queue.Queue":
    """Return (creating if needed) the event queue for a task."""
    q = _queues.get(task_id)
    if q is None:
        q = queue.Queue()
        _queues[task_id] = q
    return q


def emit(task_id: str, event: str, action: Optional[str] = None, **data: Any) -> None:
    """Push an event onto the task's queue.

    `event`  — event type (stage_started, stage_progress, node_complete, error…)
    `action` — optional human string describing the current activity, e.g.
               "Generating code with gpt-4o" or "Executing pytest".
    """
    if not task_id:
        return
    payload = {"event": event, **data}
    if action is not None:
        payload["action"] = action
    get_queue(task_id).put(payload)


def close(task_id: str) -> None:
    """Signal the drain loop that no more events are coming, then drop the queue."""
    q = _queues.get(task_id)
    if q is not None:
        q.put(None)


def discard(task_id: str) -> None:
    _queues.pop(task_id, None)


class StepCallbackHandler(BaseCallbackHandler):
    """LangChain callback that surfaces "LLM thinking…" style progress.

    Attach it to an LLM via `get_llm(task_id=..., stage=...)` so the UI can show
    what the model is doing during an otherwise-opaque call.
    """

    def __init__(self, task_id: str, stage: str, model: Optional[str] = None,
                 label: Optional[str] = None):
        self.task_id = task_id
        self.stage = stage
        self.model = model
        self.label = label or STAGE_LABELS.get(stage, stage)

    def on_llm_start(self, serialized, prompts, **kwargs) -> None:
        emit(self.task_id, "stage_progress", action=f"{self.label} — thinking…",
             node=self.stage)

    def on_llm_end(self, response, **kwargs) -> None:
        emit(self.task_id, "stage_progress", action=f"{self.label} — received response",
             node=self.stage)
        tokens = self._extract_usage(response)
        if tokens:
            snap = usage.record(self.task_id, self.stage, self.model, tokens[0], tokens[1])
            t = snap["totals"]
            emit(self.task_id, "usage", node=self.stage,
                 prompt_tokens=tokens[0], completion_tokens=tokens[1],
                 run_tokens=t["total"], run_cost_usd=round(t["cost_usd"], 4),
                 run_calls=t["calls"])

    def on_llm_error(self, error, **kwargs) -> None:
        emit(self.task_id, "stage_progress", action=f"{self.label} — LLM error: {error}",
             node=self.stage)

    @staticmethod
    def _extract_usage(response) -> Optional[tuple[int, int]]:
        """Pull (prompt_tokens, completion_tokens) from an LLMResult, tolerating the
        two shapes LangChain surfaces (provider llm_output vs message usage_metadata)."""
        try:
            tu = (getattr(response, "llm_output", None) or {}).get("token_usage") or {}
            if tu:
                return int(tu.get("prompt_tokens", 0)), int(tu.get("completion_tokens", 0))
        except Exception:  # noqa: BLE001
            pass
        try:
            msg = response.generations[0][0].message
            um = getattr(msg, "usage_metadata", None) or {}
            if um:
                return int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
        except Exception:  # noqa: BLE001
            pass
        return None
