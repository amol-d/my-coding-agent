"""Allowlisted command execution for the agentic coding loop.

The coding agent can run commands (tests, type-checks, linters, read-only git)
to verify its own work. This is deliberately NOT a general shell: commands are
shlex-parsed (never run through a shell), shell metacharacters are rejected, the
base binary must be on an allowlist, and execution is pinned to the target repo
with a timeout. This is the "allowlisted subprocess" tier — good enough to prove
the loop; a container-per-run sandbox is the next step for untrusted use.
"""

import shlex
import subprocess

from tools.local_repo import repo_path

# Base binaries the agent may invoke. Kept to build / test / lint / read-only.
ALLOWED_BASE = {
    "pytest", "python", "python3",
    "npm", "npx", "node", "pnpm", "yarn",
    "tsc", "ruff", "eslint",
    "ls", "cat", "pwd", "rg", "grep", "find", "head", "tail", "wc",
}

# For git, only read-only subcommands — the agent must never push/commit here;
# those go through the dedicated commit / pr_manager nodes and human gates.
ALLOWED_GIT_SUBCOMMANDS = {"diff", "status", "log", "show", "grep", "branch", "ls-files"}

# Characters that would enable chaining, redirection, or subshells.
FORBIDDEN_CHARS = set(";&|><`$\n")

MAX_OUTPUT = 4000


def run_command(command: str, timeout: int = 180) -> str:
    """Run an allowlisted command in the target repo. Returns 'exit=<n>\\n<output>'
    or an 'ERROR: ...' string the model can react to."""
    if not command or not command.strip():
        return "ERROR: empty command."
    if any(ch in command for ch in FORBIDDEN_CHARS):
        return "ERROR: shell metacharacters (; & | > < ` $) are not allowed."

    try:
        parts = shlex.split(command)
    except ValueError as e:
        return f"ERROR: could not parse command: {e}"
    if not parts:
        return "ERROR: empty command."

    base = parts[0]
    if base == "git":
        if len(parts) < 2 or parts[1] not in ALLOWED_GIT_SUBCOMMANDS:
            allowed = ", ".join(sorted(ALLOWED_GIT_SUBCOMMANDS))
            return f"ERROR: only read-only git subcommands are allowed ({allowed})."
    elif base not in ALLOWED_BASE:
        return (
            f"ERROR: command '{base}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_BASE))}, plus read-only git."
        )

    try:
        result = subprocess.run(
            parts,
            cwd=str(repo_path()),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s."
    except FileNotFoundError as e:
        return f"ERROR: executable not found: {e}"
    except Exception as e:  # noqa: BLE001 - surface anything else to the model
        return f"ERROR: {e}"

    output = (result.stdout + result.stderr).strip()
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n… (output truncated)"
    return f"exit={result.returncode}\n{output}".rstrip()
