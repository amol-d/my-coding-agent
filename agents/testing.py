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
import os
from pathlib import Path
from langchain_openai import ChatOpenAI
from tools.local_repo import repo_path, write_file, list_repo_files

llm = ChatOpenAI(model="gpt-4.1-mini", max_tokens=3000)


def _detect_test_command() -> list[str]:
    """Detect which test runner the project uses."""
    root = repo_path()
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
        return [sys.executable, "-m", "pytest", "--tb=short", "-v"]
    if (root / "package.json").exists():
        pkg = json.loads((root / "package.json").read_text())
        scripts = pkg.get("scripts", {})
        if "test" in scripts:
            return ["npm", "test", "--", "--watchAll=false"]
    # fallback
    return [sys.executable, "-m", "pytest", "--tb=short", "-v"]


def _generate_unit_tests(generated_code: dict, arch_context: str) -> dict[str, str]:
    """Ask GPT-4o to generate unit tests for the new code."""
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

    response = llm.invoke(prompt)
    try:
        content = response.content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(content)
    except Exception:
        return {}


def testing_agent(state: dict) -> dict:
    generated_code = state.get("generated_code", {})
    arch_context = state.get("arch_context", "")

    if not generated_code:
        return {
            "test_results": {"passed": False, "output": "No code to test", "test_files": {}},
            "current_stage": "testing_complete"
        }

    # generate and write unit tests into the repo
    test_files = _generate_unit_tests(generated_code, arch_context)
    for filepath, content in test_files.items():
        write_file(filepath.lstrip("/"), content)

    # run the actual project test suite
    test_command = _detect_test_command()
    try:
        result = subprocess.run(
            test_command,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(repo_path())
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        passed = False
        output = "Tests timed out after 120 seconds"
    except FileNotFoundError as e:
        passed = False
        output = f"Test runner not found: {e}"
    except Exception as e:
        passed = False
        output = str(e)

    return {
        "test_results": {
            "passed": passed,
            "output": output[:3000],
            "test_files": test_files,
            "test_command": " ".join(test_command)
        },
        "generated_code": {**generated_code, **test_files},
        "current_stage": "testing_complete"
    }