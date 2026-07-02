"""apply_patch — the anti-corruption guard: exact-match-once, atomic writes."""

from tools.patch import apply_patch
from tools.local_repo import read_file, write_file


def test_unique_match_applies(repo):
    r = apply_patch("a.py", [{"find": "def foo():", "replace": "def foo(x):"}])
    assert "Applied 1 edit" in r
    assert read_file("a.py").startswith("def foo(x):")


def test_zero_match_rejected_and_file_untouched(repo):
    r = apply_patch("a.py", [{"find": "def bar():", "replace": "x"}])
    assert r.startswith("ERROR") and "not found" in r
    assert "def foo():" in read_file("a.py")


def test_ambiguous_match_rejected(repo):
    write_file("dup.py", "x = 1\ny = 1\n")
    r = apply_patch("dup.py", [{"find": "= 1", "replace": "= 2"}])
    assert r.startswith("ERROR") and "matches 2 times" in r
    assert read_file("dup.py") == "x = 1\ny = 1\n"


def test_missing_file_rejected(repo):
    r = apply_patch("nope.py", [{"find": "a", "replace": "b"}])
    assert r.startswith("ERROR") and "does not exist" in r


def test_multi_edit_is_atomic(repo):
    # first edit is valid, second is not -> nothing should be written
    r = apply_patch("a.py", [
        {"find": "return 1", "replace": "return 2"},
        {"find": "DOES_NOT_EXIST", "replace": "x"},
    ])
    assert r.startswith("ERROR")
    assert "return 1" in read_file("a.py")   # atomic: unchanged


def test_empty_edits_rejected(repo):
    assert apply_patch("a.py", []).startswith("ERROR")
