import os
import shutil
import subprocess
import tempfile
from contextvars import ContextVar
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# The main target checkout. Individual runs operate in per-run git worktrees
# (see create_worktree) so concurrent runs don't clobber each other and a failed
# run can be discarded without touching this checkout.
REPO_PATH = Path(os.environ.get("LOCAL_REPO_PATH", "."))

# Where per-run worktrees live (outside the repo so they aren't scanned/committed).
WORKTREE_BASE = Path(os.environ.get(
    "WORKTREE_BASE", Path(tempfile.gettempdir()) / "coding-agent-worktrees"
))

# The repo path the CURRENT run/node should act on. None => the main REPO_PATH.
# A ContextVar (not a global) so 4 concurrent runs in the executor don't race;
# each repo-touching node sets it from state["worktree_path"] at entry.
_active_repo: ContextVar[str | None] = ContextVar("active_repo", default=None)


def set_active_repo(path: str | None) -> None:
    """Point subsequent file/git ops at a worktree (or back at the main repo)."""
    _active_repo.set(path or None)


def active_root() -> Path:
    """The repo root the current context acts on: the run's worktree, else main."""
    p = _active_repo.get()
    return Path(p) if p else REPO_PATH

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
    """Resolve a path relative to the active repo root (worktree or main)."""
    return active_root().joinpath(*parts)


def _safe_path(filepath: str) -> Path:
    """Resolve filepath under the active repo root, rejecting path traversal.

    File paths come from LLM output, so `../` (or an absolute/symlinked path) must
    not be able to read or write outside the target repo. Raises ValueError on any
    path that escapes the root."""
    root = active_root().resolve()
    full = (root / filepath.lstrip("/")).resolve()
    if full != root and root not in full.parents:
        raise ValueError(f"path escapes repository root: {filepath!r}")
    return full


def read_file(filepath: str) -> str | None:
    """Read an existing file from the repo. Returns None if missing."""
    full = _safe_path(filepath)
    if full.exists():
        return full.read_text(encoding="utf-8")
    return None


def write_file(filepath: str, content: str):
    """Write content to a file in the repo, creating dirs as needed."""
    full = _safe_path(filepath)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def list_repo_files(extensions: list[str] | None = None) -> list[str]:
    """List all files in the active repo, optionally filtered by extension."""
    root = active_root()
    results = []
    for p in root.rglob("*"):
        if p.name in IGNORE_FILES:
            continue

        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.is_file() and ".git" not in p.parts:
            rel = str(p.relative_to(root))
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


def _git(root: Path, *args) -> tuple[int, str, str]:
    """Run a git command in a specific root. Returns (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def git_run(*args) -> tuple[int, str, str]:
    """Run a git command in the active repo (worktree or main)."""
    return _git(active_root(), *args)


# ── Per-run worktree isolation ──────────────────────────────────────────────────

def _ref_exists(ref: str) -> bool:
    code, _, _ = _git(REPO_PATH, "rev-parse", "--verify", "--quiet", ref)
    return code == 0


def _resolve_base_ref(base_branch: str) -> str | None:
    """Find a usable commit-ish for the base branch: a local branch first, then the
    remote-tracking ref (a fresh clone often has only `origin/main`, no local `main`)."""
    for ref in (f"refs/heads/{base_branch}", base_branch,
                f"origin/{base_branch}", f"refs/remotes/origin/{base_branch}"):
        if _ref_exists(ref):
            return ref
    return None


def create_worktree(branch: str, base_branch: str, task_id: str) -> tuple[str | None, str]:
    """Create an isolated git worktree for a run on a fresh branch off base_branch.

    Returns (path, message). Commits made here land in the shared object DB, so the
    branch and its commits remain available from the main checkout even after the
    worktree is removed. Worktrees always target the MAIN repo, never the active one.
    """
    WORKTREE_BASE.mkdir(parents=True, exist_ok=True)
    path = WORKTREE_BASE / task_id
    if path.exists():                             # stale leftover from a prior run
        remove_worktree(str(path))

    if _ref_exists(f"refs/heads/{branch}"):
        # branch already exists (e.g. a retried run) — attach it to the worktree
        code, out, err = _git(REPO_PATH, "worktree", "add", str(path), branch)
    else:
        base = _resolve_base_ref(base_branch)
        if base is None:
            # base branch not found — don't block; branch from the repo's current
            # HEAD so the run can proceed (only fails on a repo with no commits).
            if not _ref_exists("HEAD"):
                return None, (f"base branch '{base_branch}' not found and the repo "
                              f"has no commits to branch from")
            base = "HEAD"
        code, out, err = _git(REPO_PATH, "worktree", "add", "-b", branch, str(path), base)
    if code != 0:
        return None, err or out
    return str(path), "ok"


def worktree_path_for(task_id: str) -> str:
    """The deterministic worktree location for a run — lets callers clean up by
    task_id even when they don't have the run's state (e.g. after a hard crash)."""
    return str(WORKTREE_BASE / task_id)


def remove_worktree(path: str) -> bool:
    """Remove a run's worktree (best-effort). The branch/commits survive in main."""
    if not path:
        return True
    code, _, _ = _git(REPO_PATH, "worktree", "remove", "--force", path)
    _git(REPO_PATH, "worktree", "prune")
    if code != 0 and Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)
    return code == 0


def git_current_branch() -> str:
    _, out, _ = git_run("rev-parse", "--abbrev-ref", "HEAD")
    return out


def grep_repo(pattern: str, max_results: int = 50) -> str:
    """Search tracked files for a pattern via `git grep`. Returns matching
    `path:line:text` lines (capped), or a short 'no matches' note. Newly created
    (untracked) files won't appear until committed — that's fine for context."""
    code, out, err = git_run("grep", "-n", "-I", "-e", pattern)
    if code == 0 and out:
        lines = out.splitlines()[:max_results]
        return "\n".join(lines)
    # git grep exits 1 when there are no matches; anything else is a real error.
    return "No matches." if code == 1 else (err or "No matches.")


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