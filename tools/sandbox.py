"""Command execution for the agentic coding loop, with two isolation tiers.

Tier 1 (preferred) — **per-command Docker container**: the run's worktree is
mounted at /work, the container has no network by default, dropped capabilities,
memory/cpu/pids limits, and `--rm` cleanup. This is real isolation: the agent's
commands can't touch the host.

Tier 2 (fallback) — **allowlisted host subprocess**: shlex-parsed (no shell),
metacharacters rejected, base binary allowlisted, pinned to the worktree. Used
when Docker isn't available so the system keeps working everywhere.

Selection is controlled by SANDBOX_DOCKER: `auto` (default — Docker if usable,
else host), `on` (require Docker; error if unavailable), `off` (always host).
The allowlist is enforced in BOTH tiers as defense in depth.
"""

import os
import shlex
import shutil
import subprocess
import uuid

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

# ── Configuration ───────────────────────────────────────────────────────────────
SANDBOX_MODE = os.environ.get("SANDBOX_DOCKER", "auto").lower()   # auto | on | off
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.12-slim")
SANDBOX_NETWORK = os.environ.get("SANDBOX_NETWORK", "none")       # none | bridge | host
SANDBOX_MEMORY = os.environ.get("SANDBOX_MEMORY", "2g")
SANDBOX_CPUS = os.environ.get("SANDBOX_CPUS", "2")
SANDBOX_PIDS = os.environ.get("SANDBOX_PIDS", "512")

_docker_ok: bool | None = None


def _docker_available() -> bool:
    """Whether a usable Docker daemon is reachable (cached after first check)."""
    global _docker_ok
    if _docker_ok is None:
        if shutil.which("docker") is None:
            _docker_ok = False
        else:
            try:
                _docker_ok = subprocess.run(
                    ["docker", "info"], capture_output=True, timeout=10
                ).returncode == 0
            except Exception:  # noqa: BLE001
                _docker_ok = False
    return _docker_ok


def _validate(command: str):
    """Parse + allowlist-check a command. Returns (parts, None) or (None, error)."""
    if not command or not command.strip():
        return None, "ERROR: empty command."
    if any(ch in command for ch in FORBIDDEN_CHARS):
        return None, "ERROR: shell metacharacters (; & | > < ` $) are not allowed."
    try:
        parts = shlex.split(command)
    except ValueError as e:
        return None, f"ERROR: could not parse command: {e}"
    if not parts:
        return None, "ERROR: empty command."

    base = parts[0]
    if base == "git":
        if len(parts) < 2 or parts[1] not in ALLOWED_GIT_SUBCOMMANDS:
            allowed = ", ".join(sorted(ALLOWED_GIT_SUBCOMMANDS))
            return None, f"ERROR: only read-only git subcommands are allowed ({allowed})."
    elif base not in ALLOWED_BASE:
        return None, (
            f"ERROR: command '{base}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_BASE))}, plus read-only git."
        )
    return parts, None


def _docker_argv(parts: list[str], workdir: str, name: str) -> list[str]:
    """Build the hardened `docker run` argv. Pure (no side effects) so it can be
    unit-tested without a Docker daemon."""
    argv = [
        "docker", "run", "--rm", "--name", name,
        "--network", SANDBOX_NETWORK,
        "--memory", SANDBOX_MEMORY,
        "--cpus", SANDBOX_CPUS,
        "--pids-limit", SANDBOX_PIDS,
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-e", "HOME=/tmp",
        "-v", f"{workdir}:/work",
        "-w", "/work",
    ]
    if os.name == "posix":
        # run as the host user so files created on the mounted worktree aren't root-owned
        argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
    argv += [SANDBOX_IMAGE, *parts]
    return argv


def _truncate(output: str) -> str:
    output = output.strip()
    if len(output) > MAX_OUTPUT:
        output = output[:MAX_OUTPUT] + "\n… (output truncated)"
    return output


def _run_host(parts: list[str], timeout: int) -> str:
    try:
        result = subprocess.run(
            parts, cwd=str(repo_path()), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s."
    except FileNotFoundError as e:
        return f"ERROR: executable not found: {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"
    return f"exit={result.returncode}\n{_truncate(result.stdout + result.stderr)}".rstrip()


def _run_docker(parts: list[str], timeout: int) -> str:
    name = f"agent-sbx-{uuid.uuid4().hex[:12]}"
    argv = _docker_argv(parts, str(repo_path()), name)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout + 20
        )
    except subprocess.TimeoutExpired:
        # the client was killed; force-remove the container so it can't linger
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        return f"ERROR: command timed out after {timeout}s (sandbox)."
    except Exception as e:  # noqa: BLE001
        return f"ERROR: sandbox execution failed: {e}"
    return f"exit={result.returncode}\n{_truncate(result.stdout + result.stderr)}".rstrip()


def run_command(command: str, timeout: int = 180) -> str:
    """Run an allowlisted command for the current run: in a per-run Docker
    container when available, otherwise on the host. Returns 'exit=<n>\\n<output>'
    or an 'ERROR: ...' string the model can react to."""
    parts, err = _validate(command)
    if err:
        return err

    if SANDBOX_MODE == "off":
        return _run_host(parts, timeout)
    if _docker_available():
        return _run_docker(parts, timeout)
    if SANDBOX_MODE == "on":
        return ("ERROR: SANDBOX_DOCKER=on but Docker is not available. "
                "Start Docker, or set SANDBOX_DOCKER=auto to fall back to host execution.")
    return _run_host(parts, timeout)   # auto: fall back to allowlisted host execution


def sandbox_status() -> str:
    """One-line description of how commands will run — surfaced per run for visibility."""
    if SANDBOX_MODE == "off":
        return "host allowlisted subprocess (sandbox off)"
    if _docker_available():
        return f"docker sandbox ({SANDBOX_IMAGE}, network={SANDBOX_NETWORK})"
    if SANDBOX_MODE == "on":
        return "docker required but unavailable — commands will error"
    return "host allowlisted subprocess (Docker not available)"
