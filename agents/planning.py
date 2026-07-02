"""Planning agent — produce an implementation plan for human review.

Runs before any code is written so the human can approve/steer the approach at
the hitl_plan checkpoint. Incorporates human feedback on revise loops.
"""

from dotenv import load_dotenv
load_dotenv()

from events import emit
from llm import get_llm
from tools.local_repo import list_repo_files

STAGE = "plan"


def planning_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    emit(task_id, "stage_started", action="Drafting implementation plan", node=STAGE)

    clarified_spec = state.get("clarified_spec") or state.get("raw_instructions") or ""
    arch_context = state.get("arch_context", "")
    # feedback from a previous hitl_plan "revise" decision, if any
    plan_feedback = state.get("hitl_feedback", {}).get("plan", "")

    emit(task_id, "stage_progress", action="Scanning repository structure", node=STAGE)
    repo_files = list_repo_files(extensions=[".py", ".ts", ".tsx", ".js", ".json"])
    files_blob = "\n".join(repo_files[:60]) if repo_files else "Empty repository."

    revision_note = (
        f"\n\nThe human reviewed the previous plan and asked for changes:\n{plan_feedback}\n"
        if plan_feedback else ""
    )

    prompt = f"""You are a senior engineer planning a change to an existing codebase.

SPECIFICATION:
{clarified_spec}

ARCHITECTURE GUIDELINES:
{arch_context}

EXISTING FILES (sample):
{files_blob}
{revision_note}
Produce a concrete implementation plan a reviewer can approve. Cover:
1. Approach / high-level design
2. Files to create or modify (with a one-line reason each)
3. Test strategy (what to unit test)
4. Risks / assumptions

Return clear, well-structured markdown."""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=2500)
    response = llm.invoke(prompt)
    implementation_plan = response.content.strip()

    emit(task_id, "node_complete", node=STAGE)
    return {
        "implementation_plan": implementation_plan,
        "current_stage": "plan_ready",
    }
