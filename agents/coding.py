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
    read_file, git_create_branch, git_checkout, git_current_branch,
)

DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")
STAGE = "coding"

# Hard cap on model turns so a confused loop can't run forever. Each turn may
# issue several tool calls, so real changes usually finish well under this.
MAX_AGENT_STEPS = int(os.environ.get("CODING_MAX_STEPS", "24"))


def _resolve_branch(state: dict, task_id: str):
    """Honor the 'don't create a new branch' directive; otherwise use/reuse a
    dedicated feature branch. Returns (branch_name, error_or_None)."""
    if not state.get("create_new_branch", True):
        branch = state.get("branch_name") or git_current_branch()
        emit(task_id, "stage_progress", action=f"Using existing branch {branch}", node=STAGE)
        return branch, None

    branch = state.get("branch_name") or f"agent/{task_id[:8]}"
    if git_current_branch() != branch:
        git_checkout(DEFAULT_BRANCH)
        ok, msg = git_create_branch(branch)
        if not ok:
            return branch, f"Could not create branch: {msg}"
    return branch, None


def _system_prompt(arch_context: str, plan: str, feedback: str) -> str:
    revision = (
        f"\n\nA human REJECTED your previous attempt with this feedback — address it:\n{feedback}\n"
        if feedback else ""
    )
    return f"""You are a senior software engineer working directly in an existing repository.
Fulfill the task by exploring the codebase and making targeted edits with your tools.

ARCHITECTURE GUIDELINES:
{arch_context}

APPROVED IMPLEMENTATION PLAN:
{plan or "N/A"}
{revision}
How to work:
- First explore: use list_files / grep / read_file to understand the existing code,
  conventions, and the exact files you need to change. Do NOT guess file contents.
- Edit existing files with apply_patch (read the file first so each 'find' matches
  exactly once). Use create_file only for genuinely new files.
- Match the surrounding code's style, patterns, and conventions precisely.
- Keep the change minimal and scoped to the task — do not refactor unrelated code.
- When useful, run tests/linters/type-checks with run_command and fix what you find.
- Call finish with a short summary once the change is complete and consistent.

File paths are always relative to the repo root and never start with '/'."""


def coding_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    clarified_spec = state.get("clarified_spec") or state.get("raw_instructions") or ""
    emit(task_id, "stage_started", action="Generating code changes", node=STAGE)

    if not clarified_spec:
        emit(task_id, "error", message="No task specification found", node=STAGE)
        return {"error": "No task specification found", "current_stage": "error"}

    feedback = state.get("hitl_feedback", {}).get("code_review", "")
    retry_count = state.get("code_retry_count", 0)

    branch_name, branch_err = _resolve_branch(state, task_id)
    if branch_err:
        emit(task_id, "error", message=branch_err, node=STAGE)
        return {"error": branch_err, "current_stage": "error"}

    arch_context = state.get("arch_context") or get_arch_context(clarified_spec)
    plan = state.get("implementation_plan", "")

    tracker = Tracker()
    tools, tool_map = make_tools(tracker)
    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=4096).bind_tools(tools)

    messages = [
        SystemMessage(content=_system_prompt(arch_context, plan, feedback)),
        HumanMessage(content=f"TASK:\n{clarified_spec}"),
    ]

    emit(task_id, "stage_progress", action="Exploring the codebase", node=STAGE)
    finished = False
    for step in range(MAX_AGENT_STEPS):
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
