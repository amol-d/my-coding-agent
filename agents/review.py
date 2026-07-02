# from dotenv import load_dotenv
#
# load_dotenv()
#
# from langchain_openai import ChatOpenAI
# import json
#
# llm = ChatOpenAI(model="gpt-4o", max_tokens=2048)
#
#
# def review_agent(state: dict) -> dict:
#     generated_code = state.get("generated_code", {})
#     arch_context = state.get("arch_context", "")
#
#     if not generated_code:
#         return {
#             "review_comments": [],
#             "current_stage": "review_complete"
#         }
#
#     code_str = json.dumps(generated_code, indent=2)
#
#     prompt = f"""Review the following code. Check for:
# - Correctness and logic errors
# - Security vulnerabilities
# - Adherence to clean code principles
# - Consistency with the architecture context provided
#
# ARCHITECTURE CONTEXT:
# {arch_context}
#
# CODE TO REVIEW:
# {code_str}
#
# Return a JSON array of comments. Each item must have exactly this shape:
# {{"file": "filename", "line": null, "severity": "blocking" or "suggestion", "comment": "description"}}
# Only return the JSON array, nothing else. No markdown fences."""
#
#     response = llm.invoke(prompt)
#
#     try:
#         content = response.content.strip()
#         content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
#         comments = json.loads(content)
#         if not isinstance(comments, list):
#             comments = [{"file": "general", "line": None,
#                          "severity": "suggestion", "comment": str(comments)}]
#     except Exception:
#         comments = [{"file": "general", "line": None,
#                      "severity": "suggestion", "comment": response.content}]
#
#     return {
#         "review_comments": comments,
#         "current_stage": "review_complete"
#     }

from dotenv import load_dotenv
load_dotenv()

import json
import subprocess
import sys
from events import emit
from llm import get_llm
from tools.local_repo import repo_path, set_active_repo

STAGE = "review"


def _run_linter(filepath: str) -> str:
    """Run ruff or eslint depending on file type."""
    full = str(repo_path(filepath))
    if filepath.endswith(".py"):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", full, "--output-format=text"],
                capture_output=True, text=True, timeout=30
            )
            return result.stdout + result.stderr
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""   # ruff not available — skip silently
    if filepath.endswith((".ts", ".tsx", ".js", ".jsx")):
        try:
            result = subprocess.run(
                ["npx", "eslint", full, "--format=compact"],
                capture_output=True, text=True, timeout=30,
                cwd=str(repo_path())
            )
            return result.stdout + result.stderr
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""
    return ""

def review_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    set_active_repo(state.get("worktree_path"))
    emit(task_id, "stage_started", action="Reviewing generated code", node=STAGE)
    generated_code = state.get("generated_code", {})
    arch_context = state.get("arch_context", "")

    if not generated_code:
        emit(task_id, "node_complete", node=STAGE)
        return {"review_comments": [], "current_stage": "review_complete"}

    # run linters first
    emit(task_id, "stage_progress", action="Running linters (ruff / eslint)", node=STAGE)
    lint_output = {}
    for filepath in generated_code:
        lint_result = _run_linter(filepath.lstrip("/"))
        if lint_result.strip():
            lint_output[filepath] = lint_result.strip()

    lint_summary = "\n\n".join(
        f"{fp}:\n{out}" for fp, out in lint_output.items()
    ) if lint_output else "No linting issues found."

    acceptance = (state.get("plan", {}) or {}).get("acceptance_criteria", [])
    criteria_blob = "\n".join(f"- {c}" for c in acceptance) if acceptance else "None specified."

    code_str = json.dumps(generated_code, indent=2)

    prompt = f"""Review the following code changes for an existing codebase.

ARCHITECTURE CONTEXT:
{arch_context}

ACCEPTANCE CRITERIA (from the approved plan):
{criteria_blob}

LINTER OUTPUT:
{lint_summary}

CODE CHANGES:
{code_str}

Check for:
- Whether the change satisfies EACH acceptance criterion above — mark any criterion
  that is NOT met by this code as a "blocking" comment
- Logic errors and edge cases
- Security vulnerabilities
- Breaking changes to existing interfaces
- Missing error handling
- Linter issues that need addressing

Return a JSON array. Each item must have:
{{"file": "filepath", "line": null, "severity": "blocking" or "suggestion", "comment": "description"}}
Only return the JSON array, nothing else."""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=2048)
    response = llm.invoke(prompt)

    try:
        content = response.content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        comments = json.loads(content)
        if not isinstance(comments, list):
            comments = [{"file": "general", "line": None,
                         "severity": "suggestion", "comment": str(comments)}]
    except Exception:
        comments = [{"file": "general", "line": None,
                     "severity": "suggestion", "comment": response.content}]

    emit(task_id, "node_complete", node=STAGE)
    return {
        "review_comments": comments,
        "lint_output": lint_output,
        "current_stage": "review_complete"
    }