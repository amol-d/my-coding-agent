import os
import sqlite3
from typing import TypedDict, Optional, List

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, END
from agents.ingest import ingest_agent
from agents.planning import planning_agent
from agents.coding import coding_agent
from agents.review import review_agent
from agents.testing import testing_agent
from agents.commit import commit_agent
from agents.pr_manager import pr_agent
from agents.deploy import deploy_agent
from hitl.checkpoints import (
    hitl_git_ops_gate, hitl_plan_review, hitl_code_review, hitl_test_review,
    hitl_commit_gate, hitl_deploy_gate,
)

# Bound the coding retry loop so auto-reflection (blocking review / failing tests)
# and human rejections — which all re-enter coding and share this counter — can't
# spin forever. Configurable via MAX_CODE_RETRIES.
MAX_CODE_RETRIES = int(os.environ.get("MAX_CODE_RETRIES", "3"))


class PipelineState(TypedDict, total=False):
    task_id: str
    raw_instructions: str
    uploaded_docs: List[str]
    design_inputs: List[dict]      # parsed docs/images: {name, kind, text}
    figma_links: List[str]
    options: dict                  # {create_pr: bool, deploy: bool}
    intent_type: str               # code_change | git_ops | mixed
    create_new_branch: bool        # honor "don't create a new branch"
    base_branch: Optional[str]     # target branch for a PR, from NL ("PR to dev")
    arch_context: str
    clarified_spec: str
    implementation_plan: str       # human-readable markdown, rendered from `plan`
    plan: dict                     # structured: files_to_touch, acceptance_criteria, …
    generated_code: dict
    original_code: dict            # original file contents for diff
    branch_name: str               # git branch created for this task
    worktree_path: Optional[str]   # isolated per-run git worktree (None = main checkout)
    written_files: List[str]       # files written to repo
    lint_output: dict              # linter results per file
    review_comments: List[dict]
    test_results: dict
    commit_sha: Optional[str]
    code_retry_count: int
    pr_url: Optional[str]
    deploy_status: Optional[str]
    hitl_decisions: dict
    hitl_feedback: dict
    current_stage: str
    error: Optional[str]


# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_ingest(state: dict) -> str:
    if state.get("error"):
        return "abort"
    # a pure git operation skips code generation and goes straight to the ops gate
    return "git_ops" if state.get("intent_type") == "git_ops" else "plan"


def route_after_git_ops(state: dict) -> str:
    if state.get("error"):
        return "end"
    decision = state.get("hitl_decisions", {}).get("git_ops", "approved")
    return "pr" if decision in ("approved", "override") else "end"


def route_after_plan(state: dict) -> str:
    if state.get("error"):
        return "abort"
    decision = state.get("hitl_decisions", {}).get("plan", "approved")
    return "coding" if decision in ("approved", "override") else "revise"


def route_after_coding(state: dict) -> str:
    """A coding failure (e.g. worktree/branch setup, no spec) must abort the run —
    not drag the human through meaningless review/test/commit gates on empty output."""
    return "abort" if state.get("error") else "review"


def route_after_review(state: dict) -> str:
    """Auto-reflect on BLOCKING review comments before bothering the human: loop
    back to coding to self-fix, bounded by the retry budget. Otherwise, hand the
    (converged or budget-exhausted) code to the human gate."""
    if state.get("error"):
        return "human"
    if state.get("code_retry_count", 0) >= MAX_CODE_RETRIES:
        return "human"
    blocking = [c for c in state.get("review_comments", []) or []
                if c.get("severity") == "blocking"]
    return "reflect" if blocking else "human"


def route_after_testing(state: dict) -> str:
    """Auto-reflect on a real test failure (not skipped / no-runner) before the
    human gate: loop back to coding with the failure output, bounded by budget."""
    if state.get("error"):
        return "human"
    if state.get("code_retry_count", 0) >= MAX_CODE_RETRIES:
        return "human"
    if state.get("test_results", {}).get("status") == "failed":
        return "reflect"
    return "human"


def should_retry_code(state: dict) -> str:
    if state.get("error"):                     # surface errors instead of looping
        return "proceed_to_tests"
    if state.get("code_retry_count", 0) >= MAX_CODE_RETRIES:
        return "proceed_to_tests"              # give up retrying, let a human decide
    decision = state.get("hitl_decisions", {}).get("code_review", "approved")
    return "retry_code" if decision == "rejected" else "proceed_to_tests"


def should_proceed_commit(state: dict) -> str:
    if state.get("error"):
        return "commit_gate"
    decision = state.get("hitl_decisions", {}).get("test_review", "approved")
    if decision == "rejected":
        return "retry_code"
    if decision == "abort":
        return "abort"
    return "commit_gate"                        # approved / override


def route_after_commit_gate(state: dict) -> str:
    if state.get("error"):
        return "abort"
    decision = state.get("hitl_decisions", {}).get("commit", "approved")
    return "commit" if decision in ("approved", "override") else "abort"


def _opts(state: dict) -> dict:
    return state.get("options", {}) or {}


def route_post_commit(state: dict) -> str:
    if state.get("error"):
        return "end"
    if _opts(state).get("create_pr"):
        return "pr"
    if _opts(state).get("deploy"):
        return "deploy_gate"
    return "end"


def route_post_pr(state: dict) -> str:
    if state.get("error"):
        return "end"
    return "deploy_gate" if _opts(state).get("deploy") else "end"


def route_after_deploy_gate(state: dict) -> str:
    if state.get("error"):
        return "end"
    decision = state.get("hitl_decisions", {}).get("deploy_gate", "approved")
    return "deploy" if decision in ("approved", "override") else "end"


# Persistent checkpointer: runs and their HITL interrupt state survive a backend
# restart or crash, so a paused run can still be resumed. Falls back to a file in
# the working dir; override with CHECKPOINT_DB_PATH.
CHECKPOINT_DB_PATH = os.environ.get("CHECKPOINT_DB_PATH", "checkpoints.sqlite")


def _build_checkpointer() -> SqliteSaver:
    # check_same_thread=False: the graph is streamed from a ThreadPoolExecutor, so
    # the connection is used by worker threads other than the one that opened it.
    conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")   # better concurrent read/write
    saver = SqliteSaver(conn)
    saver.setup()                               # create checkpoint tables if absent
    return saver


memory = _build_checkpointer()


def build_graph():
    builder = StateGraph(PipelineState)

    # nodes
    builder.add_node("ingest", ingest_agent)
    builder.add_node("hitl_git_ops", hitl_git_ops_gate)
    builder.add_node("plan", planning_agent)
    builder.add_node("hitl_plan", hitl_plan_review)
    builder.add_node("coding", coding_agent)
    builder.add_node("review", review_agent)
    builder.add_node("hitl_code", hitl_code_review)
    builder.add_node("testing", testing_agent)
    builder.add_node("hitl_tests", hitl_test_review)
    builder.add_node("hitl_commit", hitl_commit_gate)
    builder.add_node("commit", commit_agent)
    builder.add_node("pr_manager", pr_agent)
    builder.add_node("hitl_deploy", hitl_deploy_gate)
    builder.add_node("deploy", deploy_agent)

    # ingest classifies intent: pure git-ops skips codegen, everything else plans
    builder.set_entry_point("ingest")
    builder.add_conditional_edges("ingest", route_after_ingest, {
        "git_ops": "hitl_git_ops",
        "plan": "plan",
        "abort": END,
    })
    # git-ops fast path: confirm, then push (+ optional PR) via pr_manager
    builder.add_conditional_edges("hitl_git_ops", route_after_git_ops, {
        "pr": "pr_manager",
        "end": END,
    })
    builder.add_edge("plan", "hitl_plan")
    builder.add_conditional_edges("hitl_plan", route_after_plan, {
        "coding": "coding",
        "revise": "plan",
        "abort": END,
    })

    # code → review → (auto-reflect on blocking issues | human gate)
    builder.add_conditional_edges("coding", route_after_coding, {
        "review": "review",
        "abort": END,
    })
    builder.add_conditional_edges("review", route_after_review, {
        "reflect": "coding",     # self-fix blocking review comments (bounded)
        "human": "hitl_code",
    })
    builder.add_conditional_edges("hitl_code", should_retry_code, {
        "retry_code": "coding",
        "proceed_to_tests": "testing",
    })

    # tests → (auto-reflect on real failures | human gate)
    builder.add_conditional_edges("testing", route_after_testing, {
        "reflect": "coding",     # self-fix failing tests (bounded)
        "human": "hitl_tests",
    })
    builder.add_conditional_edges("hitl_tests", should_proceed_commit, {
        "retry_code": "coding",
        "commit_gate": "hitl_commit",
        "abort": END,
    })

    # commit gate → commit (never pushes)
    builder.add_conditional_edges("hitl_commit", route_after_commit_gate, {
        "commit": "commit",
        "abort": END,
    })

    # after commit: optional PR / deploy per run options
    builder.add_conditional_edges("commit", route_post_commit, {
        "pr": "pr_manager",
        "deploy_gate": "hitl_deploy",
        "end": END,
    })
    builder.add_conditional_edges("pr_manager", route_post_pr, {
        "deploy_gate": "hitl_deploy",
        "end": END,
    })
    builder.add_conditional_edges("hitl_deploy", route_after_deploy_gate, {
        "deploy": "deploy",
        "end": END,
    })
    builder.add_edge("deploy", END)

    # HITL nodes call interrupt() internally; interrupt_before would pause twice.
    app = builder.compile(checkpointer=memory)
    return app


pipeline = build_graph()


if __name__ == "__main__":
    # Regenerate the flow diagram: python graph.py
    try:
        pipeline.get_graph().draw_mermaid_png(
            output_file_path="./flow_control_production2Jul.png"
        )
        print("Wrote flow_control_production_2Jul.png")
    except Exception as e:  # noqa: BLE001
        print(f"Could not render PNG (needs graphviz/mermaid): {e}")
