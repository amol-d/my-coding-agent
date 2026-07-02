"""Filesystem helpers: read/write, extension filtering, ignore dirs, grep."""

import tools.local_repo as lr


def test_read_write_roundtrip(repo):
    lr.write_file("dir/new.txt", "content")
    assert lr.read_file("dir/new.txt") == "content"
    assert lr.read_file("missing.txt") is None


def test_list_repo_files_filters_and_ignores(repo):
    lr.write_file("keep.py", "x")
    lr.write_file("node_modules/pkg/index.js", "y")   # ignored dir
    lr.write_file("pkg/package-lock.json", "{}")      # ignored file
    py = lr.list_repo_files(extensions=[".py"])
    assert "keep.py" in py and "a.py" in py
    assert not any("node_modules" in f for f in lr.list_repo_files())
    assert not any(f.endswith("package-lock.json") for f in lr.list_repo_files())


def test_grep_repo_matches_tracked_files(repo):
    out = lr.grep_repo("def foo")            # a.py is committed => tracked
    assert "a.py" in out
    assert lr.grep_repo("zzz_no_such_symbol") == "No matches."
