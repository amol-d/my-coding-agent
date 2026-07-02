"""Commit agent — stage and commit the generated changes to the feature branch.

Per project requirement this commits ONLY; it never pushes. Pushing (and PR
creation) happens later in pr_manager, and only when the run opts into it.
"""

from dotenv import load_dotenv
load_dotenv()

from events import emit
from tools.local_repo import git_add_all, git_commit, git_status, git_run

STAGE = "commit"


def commit_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    emit(task_id, "stage_started", action="Staging changes", node=STAGE)

    branch_name = state.get("branch_name")
    if not branch_name:
        emit(task_id, "error", message="No branch_name in state", node=STAGE)
        return {"error": "No branch_name in state", "current_stage": "error"}

    clarified_spec = (
        state.get("clarified_spec") or state.get("raw_instructions") or "Agent task"
    )

    git_add_all()
    status = git_status()
    if not status.strip():
        emit(task_id, "error", message="No changes to commit", node=STAGE)
        return {"error": "No changes to commit", "current_stage": "error"}

    emit(task_id, "stage_progress", action="Committing (no push)", node=STAGE)
    commit_msg = f"agent: {clarified_spec[:72]}"
    ok, msg = git_commit(commit_msg)
    if not ok and "nothing to commit" not in msg:
        emit(task_id, "error", message=f"Commit failed: {msg}", node=STAGE)
        return {"error": f"Commit failed: {msg}", "current_stage": "error"}

    _, sha, _ = git_run("rev-parse", "HEAD")

    emit(task_id, "node_complete", node=STAGE)
    return {
        "commit_sha": sha,
        "current_stage": "committed",
    }
