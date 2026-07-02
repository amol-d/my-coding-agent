# from dotenv import load_dotenv
#
# load_dotenv()
#
# from langchain_openai import ChatOpenAI
# from arch_rag.retriever import get_arch_context
# import json
#
# llm = ChatOpenAI(model="gpt-4o", max_tokens=4096)
#
#
# def coding_agent(state: dict) -> dict:
#     # use .get() with fallbacks — state may be partial on resume
#     clarified_spec = (
#             state.get("clarified_spec")
#             or state.get("raw_instructions")
#             or ""
#     )
#
#     if not clarified_spec:
#         return {
#             "error": "No task specification found in state",
#             "current_stage": "error"
#         }
#
#     arch_context = get_arch_context(clarified_spec)
#
#     prompt = f"""You are a senior software engineer. Generate code following
# the architecture guidelines below exactly.
#
# ARCHITECTURE GUIDELINES:
# {arch_context}
#
# TASK SPECIFICATION:
# {clarified_spec}
#
# Return a JSON object where keys are file paths and values are complete file contents.
# Only return the JSON, nothing else."""
#
#     response = llm.invoke(prompt)
#
#     try:
#         content = response.content.strip()
#         content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
#         code = json.loads(content)
#     except Exception:
#         code = {"generated_output.txt": response.content}
#
#     return {
#         "generated_code": code,
#         "arch_context": arch_context,
#         "current_stage": "code_generated"
#     }
from dotenv import load_dotenv
load_dotenv()

import json
from arch_rag.retriever import get_arch_context
from events import emit
from llm import get_llm
from tools.local_repo import (
    list_repo_files, get_existing_code_context,
    write_file, git_create_branch, git_checkout,
    git_current_branch, read_file
)
import os

DEFAULT_BRANCH = os.environ.get("DEFAULT_BRANCH", "main")
STAGE = "coding"


def coding_agent(state: dict) -> dict:
    clarified_spec = (
        state.get("clarified_spec")
        or state.get("raw_instructions")
        or ""
    )
    task_id = state.get("task_id", "unknown")
    emit(task_id, "stage_started", action="Generating code changes", node=STAGE)

    if not clarified_spec:
        emit(task_id, "error", message="No task specification found", node=STAGE)
        return {"error": "No task specification found", "current_stage": "error"}

    # feedback from a previous hitl_code "rejected" decision, if any
    code_feedback = state.get("hitl_feedback", {}).get("code_review", "")
    retry_count = state.get("code_retry_count", 0)

    # create a feature branch for this task (reuse it on retries)
    branch_name = state.get("branch_name") or f"agent/{task_id[:8]}"
    if git_current_branch() != branch_name:
        git_checkout(DEFAULT_BRANCH)
        ok, msg = git_create_branch(branch_name)
        if not ok:
            emit(task_id, "error", message=f"Could not create branch: {msg}", node=STAGE)
            return {"error": f"Could not create branch: {msg}", "current_stage": "error"}

    # get architecture context from RAG (reuse ingest's if present)
    arch_context = state.get("arch_context") or get_arch_context(clarified_spec)
    implementation_plan = state.get("implementation_plan", "")

    # gather relevant existing files as context
    emit(task_id, "stage_progress", action="Reading existing files for context", node=STAGE)
    existing_files = list_repo_files(extensions=[".py", ".ts", ".tsx", ".js", ".json"])
    # limit to 20 most relevant files to avoid token overflow
    context_files = existing_files[:20]
    existing_code_context = get_existing_code_context(context_files)

    revision_note = (
        f"\n\nThe human REJECTED the previous attempt with this feedback — address it:\n{code_feedback}\n"
        if code_feedback else ""
    )

    prompt = f"""You are a senior software engineer working on an existing codebase.
Generate code changes to fulfill the task below.

ARCHITECTURE GUIDELINES:
{arch_context}

APPROVED IMPLEMENTATION PLAN:
{implementation_plan or "N/A"}

EXISTING CODEBASE (relevant files):
{existing_code_context}

TASK:
{clarified_spec}
{revision_note}
Rules:
- File paths must be relative to the repo root, never start with /
- Follow the exact same coding style, patterns, and conventions as the existing code
- Only create or modify files that are necessary for the task
- For modified files, return the COMPLETE updated file content, not just the diff

Return a JSON object where keys are relative file paths and values are complete file contents.
Only return the JSON, nothing else, no markdown fences."""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=4096)
    response = llm.invoke(prompt)

    try:
        content = response.content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        generated_code = json.loads(content)
    except Exception:
        generated_code = {"generated_output.txt": response.content}

    # write files to the local repo
    emit(task_id, "stage_progress", action="Writing files to the repository", node=STAGE)
    written = []
    original_contents = {}
    for filepath, file_content in generated_code.items():
        filepath = filepath.lstrip("/")
        # save original content for diff display in UI
        original_contents[filepath] = read_file(filepath) or ""
        write_file(filepath, file_content)
        written.append(filepath)

    emit(task_id, "node_complete", node=STAGE)
    return {
        "generated_code": generated_code,
        "original_code": original_contents,
        "arch_context": arch_context,
        "branch_name": branch_name,
        "written_files": written,
        "code_retry_count": retry_count + 1,
        # clear consumed feedback so a later approval doesn't re-trigger a revision
        "hitl_feedback": {**state.get("hitl_feedback", {}), "code_review": ""},
        "current_stage": "code_generated"
    }