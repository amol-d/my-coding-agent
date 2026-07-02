from langgraph.types import interrupt


def hitl_git_ops_gate(state: dict) -> dict:
    """Confirm an outward-facing git operation (push branch / open PR) that was
    requested via natural language, before it runs."""
    opts = state.get("options", {}) or {}
    decision = interrupt({
        "checkpoint": "git_ops",
        "stage": "Confirm the requested git operation",
        "payload": {
            "branch_name": state.get("branch_name", ""),
            "base_branch": state.get("base_branch") or "",
            "create_pr": opts.get("create_pr", False),
            "deploy": opts.get("deploy", False),
            "instructions": state.get("raw_instructions", ""),
        },
    })
    return {
        "hitl_decisions": {**state.get("hitl_decisions", {}),
                           "git_ops": decision["action"]},
        "hitl_feedback": {**state.get("hitl_feedback", {}),
                          "git_ops": decision.get("feedback", "")},
    }


def hitl_plan_review(state: dict) -> dict:
    """Pause for the human to approve, revise, or add input to the plan."""
    decision = interrupt({
        "checkpoint": "plan",
        "stage": "Review the implementation plan before coding",
        "payload": {"implementation_plan": state.get("implementation_plan", "")},
        "clarified_spec": state.get("clarified_spec", ""),
    })
    return {
        "hitl_decisions": {**state.get("hitl_decisions", {}),
                           "plan": decision["action"]},
        "hitl_feedback": {**state.get("hitl_feedback", {}),
                          "plan": decision.get("feedback", "")},
    }


def hitl_commit_gate(state: dict) -> dict:
    """Pause for the human to approve committing the changes (no push happens)."""
    decision = interrupt({
        "checkpoint": "commit",
        "stage": "Approve committing the generated changes",
        "payload": {
            "written_files": state.get("written_files", []),
            "branch_name": state.get("branch_name", ""),
        },
    })
    return {
        "hitl_decisions": {**state.get("hitl_decisions", {}),
                           "commit": decision["action"]},
        "hitl_feedback": {**state.get("hitl_feedback", {}),
                          "commit": decision.get("feedback", "")},
    }


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
