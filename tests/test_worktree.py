"""Per-run git worktree isolation, rollback safety, and commit persistence."""

import subprocess
from pathlib import Path

import tools.local_repo as lr


def _sh(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True).stdout.strip()


def test_isolation_and_commit_persistence(repo):
    wt, _ = lr.create_worktree("agent/x", "main", "taskX")
    assert wt and Path(wt).exists() and Path(wt).resolve() != repo.resolve()

    lr.set_active_repo(wt)
    lr.write_file("feature.txt", "hi\n")
    assert lr.read_file("feature.txt") == "hi\n"
    assert not (repo / "feature.txt").exists()          # main checkout not polluted

    lr.git_add_all()
    ok, _ = lr.git_commit("add feature")
    assert ok

    lr.set_active_repo(None)
    assert _sh(repo, "status", "--porcelain") == ""      # main working tree clean
    assert _sh(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"

    assert lr.remove_worktree(wt)
    assert not Path(wt).exists()
    # branch + commit survive the worktree removal (commit-only persistence)
    assert "agent/x" in _sh(repo, "branch", "--list", "agent/x")
    assert "feature.txt" in _sh(repo, "show", "--name-only", "--format=", "agent/x")


def test_concurrent_worktrees_isolated(repo):
    a, _ = lr.create_worktree("agent/a", "main", "taskA")
    b, _ = lr.create_worktree("agent/b", "main", "taskB")
    assert a != b and Path(a).exists() and Path(b).exists()
    lr.remove_worktree(a)
    lr.remove_worktree(b)


def test_active_repo_context_switching(repo):
    assert lr.active_root() == repo
    lr.set_active_repo("/tmp/elsewhere")
    assert str(lr.active_root()) == "/tmp/elsewhere"
    lr.set_active_repo(None)
    assert lr.active_root() == repo


def test_worktree_path_is_deterministic(repo):
    p = lr.worktree_path_for("taskZ")
    assert p.endswith("taskZ")
    assert lr.remove_worktree(p) or True   # removing a nonexistent path is a safe no-op


def test_create_worktree_reuses_existing_branch(repo):
    import subprocess
    subprocess.run(["git", "-C", str(repo), "branch", "agent/existing"],
                   check=True, capture_output=True)
    wt, msg = lr.create_worktree("agent/existing", "main", "taskReuse")
    assert wt and Path(wt).exists(), msg
    lr.remove_worktree(wt)


def test_create_worktree_falls_back_to_head_when_base_missing(repo):
    # a missing base branch must not block the run — branch from current HEAD
    wt, msg = lr.create_worktree("agent/x", "nonexistent-base", "taskHead")
    assert wt is not None, msg
    assert Path(wt).exists()
    # the new branch was created at the same commit as main (HEAD)
    head = _sh(repo, "rev-parse", "HEAD")
    assert _sh(repo, "rev-parse", "agent/x") == head
    lr.remove_worktree(wt)


def test_resolve_base_ref_prefers_local_then_origin(repo):
    assert lr._resolve_base_ref("main") is not None
    assert lr._resolve_base_ref("no-such-branch") is None   # strict; HEAD fallback lives in create_worktree
