from langgraph.types import interrupt


def hitl_code_review(state: dict) -> dict:
    """Pause here and wait for human to approve/reject/edit the generated code."""
    decision = interrupt({
        "checkpoint": "code_review",
        "stage": "Review generated code before proceeding",
        "payload": state.get("generated_code", {}),
        "review_comments": state["review_comments"]
    })

    if decision["action"] == "edit":
        return {
            "generated_code": decision["edited_code"],
            "hitl_decisions": {**state.get("hitl_decisions", {}),
                               "code_review": "edited"},
            "hitl_feedback": {**state.get("hitl_feedback", {}),
                              "code_review": decision.get("feedback", "")}
        }

    return {
        "hitl_decisions": {**state.get("hitl_decisions", {}),
                           "code_review": decision["action"]},
        "hitl_feedback": {**state.get("hitl_feedback", {}),
                          "code_review": decision.get("feedback", "")}
    }


def hitl_test_review(state: dict) -> dict:
    decision = interrupt({
        "checkpoint": "test_review",
        "stage": "Review test results before creating PR",
        "payload": state.get("test_results", {}),
    })
    return {
        "hitl_decisions": {**state.get("hitl_decisions", {}),
                           "test_review": decision["action"]}
    }


def hitl_deploy_gate(state: dict) -> dict:
    decision = interrupt({
        "checkpoint": "deploy_gate",
        "stage": "Approve deployment to production",
        "payload": {"pr_url": state.get("pr_url")}
    })
    return {
        "hitl_decisions": {**state.get("hitl_decisions", {}),
                           "deploy_gate": decision["action"]}
    }
