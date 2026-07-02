"""Planning agent — produce a STRUCTURED implementation plan for human review.

Runs before any code is written so the human can approve/steer the approach at
the hitl_plan checkpoint. The plan is structured (files to touch, approach, and —
critically — concrete acceptance criteria) so downstream stages can act on it:
the coding node builds to satisfy the criteria, and the review node flags any
unmet criterion as *blocking*, which the reflect loop auto-fixes. A human-readable
`implementation_plan` markdown is rendered from the structure for the gate + PR.
"""

from dotenv import load_dotenv
load_dotenv()

import json

from events import emit
from llm import get_llm
from tools.local_repo import list_repo_files

STAGE = "plan"


def _parse_plan(content: str) -> dict:
    """Parse the LLM's JSON plan defensively and normalize its shape."""
    content = content.strip()
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(content)
    return {
        "summary": str(data.get("summary", "")).strip(),
        "approach": str(data.get("approach", "")).strip(),
        "files_to_touch": data.get("files_to_touch") or [],
        "acceptance_criteria": [
            str(c).strip() for c in (data.get("acceptance_criteria") or []) if str(c).strip()
        ],
        "test_strategy": str(data.get("test_strategy", "")).strip(),
        "risks": [str(r).strip() for r in (data.get("risks") or []) if str(r).strip()],
    }


def _render_plan_text(plan: dict) -> str:
    """Render a structured plan into review-friendly markdown (pure function)."""
    sections = []
    if plan.get("summary"):
        sections.append(f"## Summary\n{plan['summary']}")
    if plan.get("approach"):
        sections.append(f"## Approach\n{plan['approach']}")
    files = plan.get("files_to_touch") or []
    if files:
        rows = []
        for f in files:
            if isinstance(f, dict):
                rows.append(f"- `{f.get('path', '?')}` — {f.get('change', '')}")
            else:
                rows.append(f"- `{f}`")
        sections.append("## Files to touch\n" + "\n".join(rows))
    criteria = plan.get("acceptance_criteria") or []
    if criteria:
        sections.append("## Acceptance criteria\n" + "\n".join(f"- [ ] {c}" for c in criteria))
    if plan.get("test_strategy"):
        sections.append(f"## Test strategy\n{plan['test_strategy']}")
    risks = plan.get("risks") or []
    if risks:
        sections.append("## Risks / assumptions\n" + "\n".join(f"- {r}" for r in risks))
    return "\n\n".join(sections).strip()


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
Produce a concrete, reviewable implementation plan. The acceptance_criteria are the
most important part: each must be a specific, verifiable pass/fail condition that a
reviewer or a unit test can check (e.g. "GET /health returns 200 with {{status:'ok'}}",
not "endpoint works").

Return ONLY a JSON object, no prose, no markdown fences, with this shape:
{{"summary": "one paragraph",
  "approach": "high-level design",
  "files_to_touch": [{{"path": "relative/path", "change": "one-line reason"}}],
  "acceptance_criteria": ["specific testable condition", "..."],
  "test_strategy": "what to unit test and how",
  "risks": ["risk or assumption", "..."]}}"""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=2500)
    response = llm.invoke(prompt)
    raw = response.content.strip()

    try:
        plan = _parse_plan(raw)
    except Exception:
        # keep going with the raw text as the summary rather than failing the run
        plan = {"summary": raw, "approach": "", "files_to_touch": [],
                "acceptance_criteria": [], "test_strategy": "", "risks": []}

    implementation_plan = _render_plan_text(plan) or raw

    emit(task_id, "node_complete", node=STAGE,
         action=f"{len(plan['acceptance_criteria'])} acceptance criteria")
    return {
        "plan": plan,
        "implementation_plan": implementation_plan,
        "current_stage": "plan_ready",
    }
