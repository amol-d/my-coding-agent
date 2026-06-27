import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

REPO_PATH = Path(os.environ.get("LOCAL_REPO_PATH", "."))

IGNORE_DIRS = {
    ".git",
    "node_modules",
    "build",
    "dist",
    ".next",
    "coverage",
    "ios",
    "android/app/build",
    ".dart_tool",
    "Pods",
}

IGNORE_FILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Podfile.lock",
    "pubspec.lock",
}

def repo_path(*parts) -> Path:
    """Resolve a path relative to the repo root."""
    return REPO_PATH.joinpath(*parts)


def read_file(filepath: str) -> str | None:
    """Read an existing file from the repo. Returns None if missing."""
    full = repo_path(filepath)
    if full.exists():
        return full.read_text(encoding="utf-8")
    return None


def write_file(filepath: str, content: str):
    """Write content to a file in the repo, creating dirs as needed."""
    full = repo_path(filepath)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def list_repo_files(extensions: list[str] | None = None) -> list[str]:
    """List all files in repo, optionally filtered by extension."""
    results = []
    for p in REPO_PATH.rglob("*"):
        if p.name in IGNORE_FILES:
            continue

        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.is_file() and ".git" not in p.parts:
            rel = str(p.relative_to(REPO_PATH))
            if extensions is None or any(rel.endswith(e) for e in extensions):
                results.append(rel)
    return results


def get_existing_code_context(filepaths: list[str]) -> str:
    """Read multiple files and return as a combined context string."""
    parts = []
    for fp in filepaths:
        content = read_file(fp)
        if content:
            parts.append(f"### {fp}\n```\n{content}\n```")
    return "\n\n".join(parts)


def git_run(*args) -> tuple[int, str, str]:
    """Run a git command in the repo. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", "-C", str(REPO_PATH), *args],
        capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def git_current_branch() -> str:
    _, out, _ = git_run("rev-parse", "--abbrev-ref", "HEAD")
    return out


def git_create_branch(branch_name: str) -> tuple[bool, str]:
    code, out, err = git_run("checkout", "-b", branch_name)
    if code != 0:
        # branch may already exist — try switching to it
        code, out, err = git_run("checkout", branch_name)
    return code == 0, err or out


def git_checkout(branch: str) -> tuple[bool, str]:
    code, out, err = git_run("checkout", branch)
    return code == 0, err or out


def git_add_all():
    git_run("add", "-A")


def git_commit(message: str) -> tuple[bool, str]:
    code, out, err = git_run("commit", "-m", message)
    return code == 0, err or out


def git_push(branch: str) -> tuple[bool, str]:
    code, out, err = git_run("push", "--set-upstream", "origin", branch)
    return code == 0, err or out


def git_diff_staged() -> str:
    _, out, _ = git_run("diff", "--cached")
    return out


def git_status() -> str:
    _, out, _ = git_run("status", "--short")
    return out