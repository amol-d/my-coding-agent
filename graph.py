from typing import TypedDict, Optional, List

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import MemorySaver
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
    hitl_plan_review, hitl_code_review, hitl_test_review,
    hitl_commit_gate, hitl_deploy_gate,
)

# Bound the coding retry loop so a persistently-rejecting reviewer can't spin forever.
MAX_CODE_RETRIES = 3


class PipelineState(TypedDict, total=False):
    task_id: str
    raw_instructions: str
    uploaded_docs: List[str]
    design_inputs: List[dict]      # parsed docs/images: {name, kind, text}
    figma_links: List[str]
    options: dict                  # {create_pr: bool, deploy: bool}
    arch_context: str
    clarified_spec: str
    implementation_plan: str
    generated_code: dict
    original_code: dict            # original file contents for diff
    branch_name: str               # git branch created for this task
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

def route_after_plan(state: dict) -> str:
    if state.get("error"):
        return "abort"
    decision = state.get("hitl_decisions", {}).get("plan", "approved")
    return "coding" if decision in ("approved", "override") else "revise"


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


memory = MemorySaver()


def build_graph():
    builder = StateGraph(PipelineState)

    # nodes
    builder.add_node("ingest", ingest_agent)
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

    # spec → plan → human gate
    builder.set_entry_point("ingest")
    builder.add_edge("ingest", "plan")
    builder.add_edge("plan", "hitl_plan")
    builder.add_conditional_edges("hitl_plan", route_after_plan, {
        "coding": "coding",
        "revise": "plan",
        "abort": END,
    })

    # code → review → human gate (with bounded retry)
    builder.add_edge("coding", "review")
    builder.add_edge("review", "hitl_code")
    builder.add_conditional_edges("hitl_code", should_retry_code, {
        "retry_code": "coding",
        "proceed_to_tests": "testing",
    })

    # tests → human gate
    builder.add_edge("testing", "hitl_tests")
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
            output_file_path="./flow_control_production.png"
        )
        print("Wrote flow_control_production.png")
    except Exception as e:  # noqa: BLE001
        print(f"Could not render PNG (needs graphviz/mermaid): {e}")
