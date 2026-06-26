# class PipelineState(TypedDict):
#     task_id: str
#     raw_instructions: str  # from UI textarea
#     uploaded_docs: List[str]  # file paths or text content
#     arch_context: str  # retrieved from RAG
#     clarified_spec: str
#     generated_code: dict  # {filename: code_string}
#     review_comments: List[str]
#     test_results: dict  # {passed: bool, output: str}
#     pr_url: Optional[str]
#     deploy_status: Optional[str]
#     hitl_decisions: dict  # {checkpoint_name: "approved"|"rejected"|"edited"}
#     hitl_feedback: dict  # {checkpoint_name: str}
#     current_stage: str
#     error: Optional[str]
#
#
# from langgraph.graph import StateGraph, END
# from langgraph.checkpoint.sqlite import SqliteSaver
# from agents.coding import coding_agent
# from agents.review import review_agent
# from agents.testing import testing_agent
# from agents.pr_manager import pr_agent
# from hitl.checkpoints import hitl_code_review, hitl_test_review, hitl_deploy_gate
#
#
# def should_retry_code(state: dict) -> str:
#     decision = state.get("hitl_decisions", {}).get("code_review", "approved")
#     return "retry_code" if decision == "rejected" else "proceed_to_tests"
#
#
# def should_proceed_deploy(state: dict) -> str:
#     decision = state.get("hitl_decisions", {}).get("test_review", "approved")
#     return "create_pr" if decision in ["approved", "override"] else "abort"
#
# _saver = SqliteSaver.from_conn_string("./pipeline_state.db")
#
# def build_graph():
#     # memory = SqliteSaver.from_conn_string("./pipeline_state.db")
#     with _saver as memory:
#         builder = StateGraph(PipelineState)
#
#         builder.add_node("coding", coding_agent)
#         builder.add_node("review", review_agent)
#         builder.add_node("hitl_code", hitl_code_review)
#         builder.add_node("testing", testing_agent)
#         builder.add_node("hitl_tests", hitl_test_review)
#         builder.add_node("pr_manager", pr_agent)
#         builder.add_node("hitl_deploy", hitl_deploy_gate)
#
#         builder.set_entry_point("coding")
#         builder.add_edge("coding", "review")
#         builder.add_edge("review", "hitl_code")
#         builder.add_conditional_edges("hitl_code", should_retry_code, {
#             "retry_code": "coding",
#             "proceed_to_tests": "testing"
#         })
#         builder.add_edge("testing", "hitl_tests")
#         builder.add_conditional_edges("hitl_tests", should_proceed_deploy, {
#             "create_pr": "pr_manager",
#             "abort": END
#         })
#         builder.add_edge("pr_manager", "hitl_deploy")
#         builder.add_edge("hitl_deploy", END)
#
#         app = builder.compile(checkpointer=memory, interrupt_before=["hitl_code", "hitl_tests", "hitl_deploy"])
#         app.get_graph().draw_mermaid_png(output_file_path=f"./flow_control.png")
#         return app
#
#
# pipeline = build_graph()


from typing import TypedDict, Optional

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from agents.coding import coding_agent
from agents.review import review_agent
from agents.testing import testing_agent
from agents.pr_manager import pr_agent
from hitl.checkpoints import hitl_code_review, hitl_test_review, hitl_deploy_gate


class PipelineState(TypedDict, total=False):
    task_id: str
    raw_instructions: str
    uploaded_docs: list[str]
    arch_context: str
    clarified_spec: str
    generated_code: dict
    review_comments: list
    test_results: dict
    pr_url: Optional[str]
    deploy_status: Optional[str]
    hitl_decisions: dict
    hitl_feedback: dict
    current_stage: str
    error: Optional[str]


def should_retry_code(state: dict) -> str:
    decision = state.get("hitl_decisions", {}).get("code_review", "approved")
    return "retry_code" if decision == "rejected" else "proceed_to_tests"


def should_proceed_deploy(state: dict) -> str:
    decision = state.get("hitl_decisions", {}).get("test_review", "approved")
    return "create_pr" if decision in ["approved", "override"] else "abort"


memory = MemorySaver()


def build_graph():
    builder = StateGraph(PipelineState)

    builder.add_node("coding", coding_agent)
    builder.add_node("review", review_agent)
    builder.add_node("hitl_code", hitl_code_review)
    builder.add_node("testing", testing_agent)
    builder.add_node("hitl_tests", hitl_test_review)
    builder.add_node("pr_manager", pr_agent)
    builder.add_node("hitl_deploy", hitl_deploy_gate)

    builder.set_entry_point("coding")
    builder.add_edge("coding", "review")
    builder.add_edge("review", "hitl_code")
    builder.add_conditional_edges("hitl_code", should_retry_code, {
        "retry_code": "coding",
        "proceed_to_tests": "testing"
    })
    builder.add_edge("testing", "hitl_tests")
    builder.add_conditional_edges("hitl_tests", should_proceed_deploy, {
        "create_pr": "pr_manager",
        "abort": END
    })
    builder.add_edge("pr_manager", "hitl_deploy")
    builder.add_edge("hitl_deploy", END)
    # HITL nodes call interrupt() internally; interrupt_before would pause twice.
    return builder.compile(checkpointer=memory)


pipeline = build_graph()
