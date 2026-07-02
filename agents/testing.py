# from dotenv import load_dotenv
#
# load_dotenv()
#
# from langchain_openai import ChatOpenAI
# import importlib.util
# import subprocess
# import tempfile
# import os
# import json
# import sys
#
# llm = ChatOpenAI(model="gpt-4o", max_tokens=3000)
#
#
# def _pytest_available() -> bool:
#     return importlib.util.find_spec("pytest") is not None
#
#
# def testing_agent(state: dict) -> dict:
#     generated_code = state.get("generated_code", {})
#
#     if not generated_code:
#         return {
#             "test_results": {
#                 "passed": False,
#                 "output": "No code to test",
#                 "test_code": ""
#             },
#             "current_stage": "testing_complete"
#         }
#
#     prompt = f"""Generate pytest unit tests for the following code.
# Only return valid Python test code. No markdown fences, no explanation.
#
# Rules:
# - Import only from the standard library or pytest
# - Do not import from the generated files directly — mock or inline the logic
# - Each test function must start with test_
# - Keep tests simple and self-contained
#
# CODE:
# {json.dumps(generated_code, indent=2)}"""
#
#     response = llm.invoke(prompt)
#     test_code = response.content.strip()
#     test_code = test_code.removeprefix("```python").removeprefix("```").removesuffix("```").strip()
#
#     if not _pytest_available():
#         return {
#             "test_results": {
#                 "passed": False,
#                 "output": (
#                     "pytest is not installed in the project environment. "
#                     "Run: poetry install  (pytest is listed in pyproject.toml)"
#                 ),
#                 "test_code": test_code,
#             },
#             "current_stage": "testing_complete",
#         }
#
#     with tempfile.NamedTemporaryFile(
#             suffix=".py", mode="w", delete=False, dir="/tmp"
#     ) as f:
#         f.write(test_code)
#         test_path = f.name
#
#     try:
#         result = subprocess.run(
#             [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
#             capture_output=True,
#             text=True,
#             timeout=60
#         )
#         passed = result.returncode == 0
#         output = result.stdout + result.stderr
#     except subprocess.TimeoutExpired:
#         passed = False
#         output = "Tests timed out after 60 seconds"
#     except Exception as e:
#         passed = False
#         output = str(e)
#     finally:
#         try:
#             os.unlink(test_path)
#         except Exception:
#             pass
#
#     return {
#         "test_results": {
#             "passed": passed,
#             "output": output[:2000],
#             "test_code": test_code
#         },
#         "current_stage": "testing_complete"
#     }

from dotenv import load_dotenv
load_dotenv()

import json
import subprocess
import sys
from pathlib import Path
from events import emit
from llm import get_llm
from tools.local_repo import repo_path, write_file, list_repo_files

STAGE = "testing"

PY_TEST_EXTS = (".py",)
JS_TEST_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
IGNORE_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage"}


def _nearest_package_json(rel_test_path: str) -> Path | None:
    """Walk up from a JS test file to find the owning package.json; fall back to
    the shallowest package.json in the repo (e.g. a `frontend/` subproject)."""
    root = repo_path().resolve()
    d = (repo_path() / rel_test_path).parent.resolve()
    while True:
        if (d / "package.json").exists():
            return d
        if d == root or d.parent == d:
            break
        d = d.parent
    candidates = [
        p.parent for p in repo_path().rglob("package.json")
        if not any(part in IGNORE_DIRS for part in p.parts)
    ]
    return min(candidates, key=lambda p: len(p.parts)) if candidates else None


def _plan_test_run(test_files: dict) -> tuple[list[str] | None, str, str, str]:
    """Choose a runner based on the generated test files' languages.

    Returns (command, cwd, kind, note). command is None when no runner applies.
    """
    paths = list(test_files.keys())
    js = [p for p in paths if p.endswith(JS_TEST_EXTS)]
    py = [p for p in paths if p.endswith(PY_TEST_EXTS)]

    # Prefer whichever language the generated tests are actually written in.
    if js and not py:
        pkg_dir = _nearest_package_json(js[0])
        if pkg_dir is None:
            return None, str(repo_path()), "js", "No package.json found for JS/TS tests."
        pkg = json.loads((pkg_dir / "package.json").read_text())
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        rel = [str((repo_path() / p).resolve().relative_to(pkg_dir)) for p in js]
        if "vitest" in deps:
            return ["npx", "vitest", "run", *rel], str(pkg_dir), "js", ""
        if "jest" in deps:
            return ["npx", "jest", *rel, "--watchAll=false"], str(pkg_dir), "js", ""
        if "test" in pkg.get("scripts", {}):
            return ["npm", "test"], str(pkg_dir), "js", "Ran project `npm test` script."
        return None, str(pkg_dir), "js", "No JS test runner (vitest/jest/test script) available."

    if py:
        cmd = [sys.executable, "-m", "pytest", *py, "--tb=short", "-v"]
        return cmd, str(repo_path()), "py", ""

    return None, str(repo_path()), "none", "No test files were generated."


def _generate_unit_tests(generated_code: dict, arch_context: str, task_id: str) -> dict[str, str]:
    """Ask the LLM to generate unit tests for the new code."""
    existing_tests = list_repo_files(extensions=["_test.py", "test_.py", ".test.ts", ".spec.ts"])
    test_context = "\n".join(existing_tests[:5]) if existing_tests else "No existing tests found."

    prompt = f"""Generate unit tests for the following new/modified code.

ARCHITECTURE CONTEXT:
{arch_context}

EXISTING TEST FILES (for style reference):
{test_context}

NEW CODE TO TEST:
{json.dumps(generated_code, indent=2)}

Rules:
- Match the exact test style and framework already used in the project
- For Python: use pytest, place tests in tests/ folder mirroring the source structure
- For TypeScript: use Jest/Vitest, place tests alongside source files as *.test.ts
- Write meaningful tests that cover happy path, edge cases, and error cases
- File paths must be relative to repo root, never start with /

Return a JSON object where keys are test file paths and values are complete test file contents.
Only return the JSON, nothing else, no markdown fences."""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=3000)
    response = llm.invoke(prompt)
    try:
        content = response.content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(content)
    except Exception:
        return {}


def testing_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    emit(task_id, "stage_started", action="Generating unit tests", node=STAGE)
    generated_code = state.get("generated_code", {})
    arch_context = state.get("arch_context", "")

    if not generated_code:
        emit(task_id, "node_complete", node=STAGE)
        return {
            "test_results": {"passed": False, "output": "No code to test", "test_files": {}},
            "current_stage": "testing_complete"
        }

    # generate and write unit tests into the repo
    test_files = _generate_unit_tests(generated_code, arch_context, task_id)
    for filepath, content in test_files.items():
        write_file(filepath.lstrip("/"), content)

    # pick a runner that matches the language of the generated tests
    command, cwd, kind, note = _plan_test_run(test_files)

    if command is None:
        # nothing to run (no tests, or no runner) — not a code failure, let the
        # human decide at the review gate.
        emit(task_id, "node_complete", node=STAGE, action=note or "No tests run")
        return {
            "test_results": {
                "passed": True, "status": "skipped", "ran": False,
                "output": note, "test_files": test_files, "test_command": "",
            },
            "generated_code": {**generated_code, **test_files},
            "current_stage": "testing_complete"
        }

    emit(task_id, "stage_progress",
         action=f"Executing tests: {' '.join(command)}", node=STAGE)
    status = "failed"
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=180, cwd=cwd
        )
        code = result.returncode
        output = result.stdout + result.stderr
        # pytest exit 5 == "no tests collected"; treat as skipped, not failure.
        if kind == "py" and code == 5:
            passed, status = True, "no_tests"
        else:
            passed = code == 0
            status = "passed" if passed else "failed"
    except subprocess.TimeoutExpired:
        passed, output = False, "Tests timed out after 180 seconds"
    except FileNotFoundError as e:
        # runner binary (e.g. npx/node) not installed — not a code failure.
        passed, status, output = True, "runner_unavailable", f"Test runner not found: {e}"
    except Exception as e:
        passed, output = False, str(e)

    action = {"passed": "Tests passed", "failed": "Tests failed",
              "no_tests": "No tests collected",
              "runner_unavailable": "Test runner unavailable"}.get(status, "Tests done")
    emit(task_id, "node_complete", node=STAGE, action=action)
    return {
        "test_results": {
            "passed": passed,
            "status": status,
            "ran": status in ("passed", "failed"),
            "output": output[:3000],
            "test_files": test_files,
            "test_command": " ".join(command),
        },
        "generated_code": {**generated_code, **test_files},
        "current_stage": "testing_complete"
    }