"""Deploy agent — optional final stage.

Deployment is environment-specific; this runs a configurable command
(`DEPLOY_COMMAND`) if one is set, otherwise it records a no-op status. Only
reached when the run opts into deploy AND the human approves the deploy gate.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import subprocess

from events import emit
from tools.local_repo import repo_path, set_active_repo

STAGE = "deploy"


def deploy_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    set_active_repo(state.get("worktree_path"))
    emit(task_id, "stage_started", action="Deploying", node=STAGE)

    command = os.environ.get("DEPLOY_COMMAND", "").strip()
    if not command:
        emit(task_id, "node_complete", node=STAGE, action="No DEPLOY_COMMAND set — skipped")
        return {"deploy_status": "skipped (no DEPLOY_COMMAND configured)",
                "current_stage": "deployed"}

    emit(task_id, "stage_progress", action=f"Running: {command}", node=STAGE)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=600, cwd=str(repo_path()),
        )
        ok = result.returncode == 0
        output = (result.stdout + result.stderr)[:2000]
    except Exception as e:  # noqa: BLE001
        emit(task_id, "error", message=f"Deploy failed: {e}", node=STAGE)
        return {"deploy_status": f"failed: {e}", "current_stage": "error"}

    status = "success" if ok else f"failed:\n{output}"
    emit(task_id, "node_complete", node=STAGE,
         action="Deploy succeeded" if ok else "Deploy failed")
    return {"deploy_status": status, "current_stage": "deployed"}
