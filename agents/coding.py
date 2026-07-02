"""Coding node — an agentic tool-use loop.

Rather than asking the model for one big JSON blob of whole files, this node
gives the model a small tool set (explore / edit / verify) and lets it iterate:
read files, grep, apply targeted patches, run tests, read failures, patch again —
until it calls ``finish`` or hits a step cap. This scales to real repos and lets
the model self-correct against actual tool output.

The node's input/output contract is unchanged, so ``review`` / ``testing`` and
every HITL gate keep working: it still returns ``generated_code`` (path→final
content), ``original_code`` (path→pre-edit content), ``branch_name`` and
``written_files``.
"""

from dotenv import load_dotenv
load_dotenv()

import os

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from arch_rag.retriever import get_arch_context
from events import emit
from llm import get_llm
from tools.agent_tools import Tracker, make_tools
from tools.local_repo import (
    read_file, git_current_branch, create_worktree, set_active_repo,
)
from tools.sandbox import sandbox_status
from usage import over_budget

DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")
STAGE = "coding"

# Hard cap on model turns so a confused loop can't run forever. Each turn may
# issue several tool calls, so real changes usually finish well under this.
MAX_AGENT_STEPS = int(os.environ.get("CODING_MAX_STEPS", "24"))


def _setup_workspace(state: dict, task_id: str):
    """Prepare an isolated workspace and point file/git ops at it.

    Returns (branch_name, worktree_path, error). For the normal case this creates
    a per-run git worktree on a fresh branch so concurrent runs don't collide and
    a failed run can be discarded without touching the main checkout. When the user
    asked to edit the CURRENT branch (create_new_branch=false), we stay on the main
    checkout since a worktree can't check out an already-checked-out branch.
    """
    existing = state.get("worktree_path")
    if existing:
        # a retry or resume within the same run — reuse the same worktree
        set_active_repo(existing)
        return state.get("branch_name"), existing, None

    if not state.get("create_new_branch", True):
        set_active_repo(None)
        branch = state.get("branch_name") or git_current_branch()
        emit(task_id, "stage_progress",
             action=f"Using current branch {branch} (main checkout)", node=STAGE)
        return branch, None, None

    branch = state.get("branch_name") or f"agent/{task_id[:8]}"
    emit(task_id, "stage_progress",
         action=f"Creating isolated worktree on {branch}", node=STAGE)
    worktree_path, msg = create_worktree(branch, DEFAULT_BRANCH, task_id)
    if worktree_path is None:
        return branch, None, f"Could not create worktree: {msg}"
    set_active_repo(worktree_path)
    return branch, worktree_path, None


def _reflection_notes(state: dict) -> str:
    """Assemble the objective signals a retry should address: human rejection
    feedback, BLOCKING automated review comments, and test-suite failures. Empty
    string on the first attempt (no signals yet)."""
    parts = []

    human_fb = state.get("hitl_feedback", {}).get("code_review", "")
    if human_fb:
        parts.append(f"A human REJECTED the previous attempt with this feedback:\n{human_fb}")

    blocking = [c for c in state.get("review_comments", []) or []
                if c.get("severity") == "blocking"]
    if blocking:
        lines = "\n".join(
            f"- {c.get('file', '?')}: {c.get('comment', '')}" for c in blocking
        )
        parts.append(f"Automated review found BLOCKING issues you must fix:\n{lines}")

    tr = state.get("test_results", {}) or {}
    if tr.get("status") == "failed":
        out = (tr.get("output", "") or "")[:1500]
        parts.append(
            "The test suite FAILED. Make the code (or the tests, if they are wrong) "
            f"correct so it passes.\nTest command: {tr.get('test_command', '')}\n"
            f"Output:\n{out}"
        )

    return "\n\n".join(parts)


def _system_prompt(arch_context: str, plan: str, acceptance: list, reflection: str) -> str:
    revision = (
        "\n\nYou are REVISING a previous attempt. Before anything else, address the "
        f"following and verify your fix with run_command:\n{reflection}\n"
        if reflection else ""
    )
    criteria = (
        "\n\nACCEPTANCE CRITERIA — your change MUST satisfy every one of these; a reviewer "
        "will check them and send unmet ones back to you:\n"
        + "\n".join(f"- {c}" for c in acceptance) + "\n"
        if acceptance else ""
    )
    return f"""You are a senior software engineer working directly in an existing repository.
Fulfill the task by exploring the codebase and making targeted edits with your tools.

ARCHITECTURE GUIDELINES:
{arch_context}

APPROVED IMPLEMENTATION PLAN:
{plan or "N/A"}
{criteria}{revision}
How to work:
- First explore: use list_files / grep / read_file to understand the existing code,
  conventions, and the exact files you need to change. Do NOT guess file contents.
- Edit existing files with apply_patch (read the file first so each 'find' matches
  exactly once). Use create_file only for genuinely new files.
- Match the surrounding code's style, patterns, and conventions precisely.
- Keep the change minimal and scoped to the task — do not refactor unrelated code.
- A dedicated review + unit-test suite runs after you finish and will send blocking
  issues or test failures back to you. Pre-empt that: run the relevant tests, linters
  and type-checks with run_command and fix what you find BEFORE calling finish.
- Call finish with a short summary once the change is complete and consistent.

File paths are always relative to the repo root and never start with '/'."""


def coding_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    clarified_spec = state.get("clarified_spec") or state.get("raw_instructions") or ""
    emit(task_id, "stage_started", action="Generating code changes", node=STAGE)
    emit(task_id, "stage_progress", action=f"Command sandbox: {sandbox_status()}", node=STAGE)

    if not clarified_spec:
        emit(task_id, "error", message="No task specification found", node=STAGE)
        return {"error": "No task specification found", "current_stage": "error"}

    reflection = _reflection_notes(state)
    retry_count = state.get("code_retry_count", 0)
    if reflection and retry_count > 0:
        emit(task_id, "stage_progress",
             action=f"Self-correcting from review/test feedback (attempt {retry_count + 1})",
             node=STAGE)

    branch_name, worktree_path, branch_err = _setup_workspace(state, task_id)
    if branch_err:
        emit(task_id, "error", message=branch_err, node=STAGE)
        return {"error": branch_err, "current_stage": "error"}

    arch_context = state.get("arch_context") or get_arch_context(clarified_spec)
    plan = state.get("implementation_plan", "")
    acceptance = (state.get("plan", {}) or {}).get("acceptance_criteria", [])

    tracker = Tracker()
    tools, tool_map = make_tools(tracker)
    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=4096).bind_tools(tools)

    messages = [
        SystemMessage(content=_system_prompt(arch_context, plan, acceptance, reflection)),
        HumanMessage(content=f"TASK:\n{clarified_spec}"),
    ]

    emit(task_id, "stage_progress", action="Exploring the codebase", node=STAGE)
    finished = False
    for step in range(MAX_AGENT_STEPS):
        if over_budget(task_id):
            emit(task_id, "stage_progress",
                 action="Run budget reached — stopping code generation", node=STAGE)
            break
        response = llm.invoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # Model replied with prose instead of acting. Nudge once toward a tool;
            # if it persists, stop and let whatever was changed flow to review.
            if step < MAX_AGENT_STEPS - 1:
                messages.append(HumanMessage(
                    content="Use a tool to make progress, or call finish if the change is complete."
                ))
                continue
            break

        stop = False
        for call in tool_calls:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            emit(task_id, "stage_progress", action=_describe(name, args), node=STAGE)

            if name == "finish":
                messages.append(ToolMessage(content="Finishing.", tool_call_id=call["id"]))
                stop = True
                finished = True
                break

            tool = tool_map.get(name)
            if tool is None:
                result = f"ERROR: unknown tool '{name}'."
            else:
                try:
                    result = tool.invoke(args)
                except Exception as e:  # noqa: BLE001 - report tool errors to the model
                    result = f"ERROR: {e}"
            messages.append(ToolMessage(content=str(result)[:4000], tool_call_id=call["id"]))

        if stop:
            break

    # Build the diff contract from the files the agent actually touched.
    generated_code: dict[str, str] = {}
    original_code: dict[str, str] = {}
    for path, original in tracker.originals.items():
        current = read_file(path)
        if current is None:
            continue  # file was created then removed, or unreadable
        generated_code[path] = current
        original_code[path] = original

    written = list(generated_code.keys())
    if written:
        emit(task_id, "node_complete", node=STAGE,
             action=f"Edited {len(written)} file(s)" + ("" if finished else " (step limit reached)"))
    else:
        emit(task_id, "node_complete", node=STAGE, action="No file changes were made")

    return {
        "generated_code": generated_code,
        "original_code": original_code,
        "arch_context": arch_context,
        "branch_name": branch_name,
        "worktree_path": worktree_path,
        "written_files": written,
        "code_retry_count": retry_count + 1,
        # clear consumed feedback so a later approval doesn't re-trigger a revision
        "hitl_feedback": {**state.get("hitl_feedback", {}), "code_review": ""},
        "current_stage": "code_generated",
    }


def _describe(name: str, args: dict) -> str:
    """Short human-readable label for a tool call, for the live activity feed."""
    if name == "apply_patch":
        n = len(args.get("edits", []) or [])
        return f"Editing {args.get('path', '?')} ({n} edit{'s' if n != 1 else ''})"
    if name == "create_file":
        return f"Creating {args.get('path', '?')}"
    if name == "read_file":
        return f"Reading {args.get('path', '?')}"
    if name == "list_files":
        return "Listing files" + (f": {args['pattern']}" if args.get("pattern") else "")
    if name == "grep":
        return f"Searching for {args.get('pattern', '?')}"
    if name == "run_command":
        return f"Running {args.get('command', '?')}"
    if name == "finish":
        return "Finalizing changes"
    return name
