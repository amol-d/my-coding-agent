from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
import importlib.util
import subprocess
import tempfile
import os
import json
import sys

llm = ChatOpenAI(model="gpt-4o", max_tokens=3000)


def _pytest_available() -> bool:
    return importlib.util.find_spec("pytest") is not None


def testing_agent(state: dict) -> dict:
    generated_code = state.get("generated_code", {})

    if not generated_code:
        return {
            "test_results": {
                "passed": False,
                "output": "No code to test",
                "test_code": ""
            },
            "current_stage": "testing_complete"
        }

    prompt = f"""Generate pytest unit tests for the following code.
Only return valid Python test code. No markdown fences, no explanation.

Rules:
- Import only from the standard library or pytest
- Do not import from the generated files directly — mock or inline the logic
- Each test function must start with test_
- Keep tests simple and self-contained

CODE:
{json.dumps(generated_code, indent=2)}"""

    response = llm.invoke(prompt)
    test_code = response.content.strip()
    test_code = test_code.removeprefix("```python").removeprefix("```").removesuffix("```").strip()

    if not _pytest_available():
        return {
            "test_results": {
                "passed": False,
                "output": (
                    "pytest is not installed in the project environment. "
                    "Run: poetry install  (pytest is listed in pyproject.toml)"
                ),
                "test_code": test_code,
            },
            "current_stage": "testing_complete",
        }

    with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False, dir="/tmp"
    ) as f:
        f.write(test_code)
        test_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        passed = False
        output = "Tests timed out after 60 seconds"
    except Exception as e:
        passed = False
        output = str(e)
    finally:
        try:
            os.unlink(test_path)
        except Exception:
            pass

    return {
        "test_results": {
            "passed": passed,
            "output": output[:2000],
            "test_code": test_code
        },
        "current_stage": "testing_complete"
    }
