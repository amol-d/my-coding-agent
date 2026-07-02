"""Security invariants: token round-trip, constant-time creds, config warnings,
and path-traversal protection on the target-repo file operations."""

import pytest

import auth
import tools.local_repo as lr


# ── JWT ─────────────────────────────────────────────────────────────────────
def test_decode_token_roundtrip():
    tok = auth.create_token("alice")
    assert auth.decode_token(tok) == "alice"


def test_decode_token_rejects_garbage_and_wrong_secret():
    assert auth.decode_token("not-a-jwt") is None
    import jwt as pyjwt
    forged = pyjwt.encode({"sub": "mallory"}, "wrong-secret", algorithm="HS256")
    assert auth.decode_token(forged) is None


# ── Credentials ─────────────────────────────────────────────────────────────
def test_verify_credentials(monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_USERNAME", "u")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "p")
    assert auth.verify_credentials("u", "p") is True
    assert auth.verify_credentials("u", "wrong") is False
    assert auth.verify_credentials("wrong", "p") is False


# ── Startup config warnings ─────────────────────────────────────────────────
def test_security_warnings_flags_defaults(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", auth._DEFAULT_SECRET)
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", auth._DEFAULT_PASSWORD)
    assert len(auth.security_warnings()) == 2

    monkeypatch.setattr(auth, "SECRET_KEY", "a-strong-secret")
    monkeypatch.setattr(auth, "ADMIN_PASSWORD", "a-strong-password")
    assert auth.security_warnings() == []


# ── Path traversal ──────────────────────────────────────────────────────────
def test_write_rejects_parent_traversal(repo, tmp_path):
    with pytest.raises(ValueError):
        lr.write_file("../escaped.txt", "x")
    with pytest.raises(ValueError):
        lr.write_file("../../etc/evil.txt", "x")
    # the escape target must NOT have been created
    assert not (tmp_path / "escaped.txt").exists()


def test_read_rejects_parent_traversal(repo):
    with pytest.raises(ValueError):
        lr.read_file("../../../etc/passwd")


def test_absolute_paths_are_neutralized_to_relative(repo):
    # a leading slash is stripped -> stays inside the repo, does not escape
    lr.write_file("/etc/passwd", "inside")
    assert lr.read_file("etc/passwd") == "inside"
    assert (repo / "etc" / "passwd").exists()


def test_legit_nested_paths_still_work(repo):
    lr.write_file("src/pkg/mod.py", "ok")
    assert lr.read_file("src/pkg/mod.py") == "ok"
