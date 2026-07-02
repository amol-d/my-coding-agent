"""Command sandbox — allowlist enforcement, hardened docker argv, mode fallback."""

import os
import tools.sandbox as sb


def test_validate_allows_known_commands():
    assert sb._validate("pytest -q")[0] == ["pytest", "-q"]
    assert sb._validate("git status")[0] == ["git", "status"]
    assert sb._validate("npx vitest run")[0] == ["npx", "vitest", "run"]


def test_validate_blocks_disallowed_and_dangerous():
    assert "not allowed" in sb._validate("curl http://x")[1]
    assert "read-only git" in sb._validate("git push origin main")[1]
    assert "metacharacters" in sb._validate("pytest && rm -rf /")[1]
    assert "metacharacters" in sb._validate("cat a.py | sh")[1]
    assert "metacharacters" in sb._validate("echo $SECRET")[1]
    assert sb._validate("   ")[1].startswith("ERROR")


def test_docker_argv_is_hardened():
    argv = sb._docker_argv(["pytest", "-q"], "/tmp/wt", "sbx1")
    s = " ".join(argv)
    for token in ["docker run --rm", "--name sbx1", "--network none",
                  "--memory", "--cpus", "--pids-limit",
                  "--cap-drop ALL", "--security-opt no-new-privileges",
                  "-e HOME=/tmp", "-v /tmp/wt:/work", "-w /work"]:
        assert token in s, f"missing {token} in {s}"
    assert argv[-3:] == [sb.SANDBOX_IMAGE, "pytest", "-q"]
    if os.name == "posix":
        assert f"--user {os.getuid()}:{os.getgid()}" in s


def test_mode_on_without_docker_errors(monkeypatch):
    monkeypatch.setattr(sb, "SANDBOX_MODE", "on")
    monkeypatch.setattr(sb, "_docker_ok", False)
    out = sb.run_command("git status")
    assert out.startswith("ERROR") and "Docker is not available" in out


def test_auto_mode_falls_back_to_host(repo, monkeypatch):
    monkeypatch.setattr(sb, "SANDBOX_MODE", "auto")
    monkeypatch.setattr(sb, "_docker_ok", False)
    out = sb.run_command("git status")
    assert out.startswith("exit=0")


def test_allowlist_blocks_before_execution(monkeypatch):
    monkeypatch.setattr(sb, "_docker_ok", False)
    assert sb.run_command("curl evil.com").startswith("ERROR")
