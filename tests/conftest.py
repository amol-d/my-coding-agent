"""Shared pytest fixtures for the agent's own test suite.

These tests exercise the agent's *deterministic* logic (routing, patching, the
sandbox allowlist, worktree isolation, option merging) — no LLM calls and no
network. The `repo` fixture wires tools.local_repo at a throwaway git repo so
file/git/worktree operations run in isolation.
"""

import os
import subprocess
import tempfile

# Keep the LangGraph checkpointer DB out of the repo when importing graph in tests.
os.environ.setdefault(
    "CHECKPOINT_DB_PATH",
    os.path.join(tempfile.gettempdir(), "agent_test_checkpoints.sqlite"),
)

import pytest


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway git repo (branch `main`, one committed file `a.py`) wired into
    tools.local_repo via REPO_PATH + WORKTREE_BASE, with the active-repo context
    reset around the test so nothing leaks between tests."""
    import tools.local_repo as lr

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "t@t.co")
    _git(repo_dir, "config", "user.name", "t")
    (repo_dir / "a.py").write_text("def foo():\n    return 1\n")
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-m", "init")

    monkeypatch.setattr(lr, "REPO_PATH", repo_dir)
    monkeypatch.setattr(lr, "WORKTREE_BASE", tmp_path / "worktrees")
    lr.set_active_repo(None)
    yield repo_dir
    lr.set_active_repo(None)
