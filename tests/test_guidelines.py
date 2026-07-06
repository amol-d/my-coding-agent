"""Architecture context is sourced from the target repo's AGENTS.md / CLAUDE.md."""

import arch_rag.retriever as r
from tools.local_repo import write_file


def test_reads_agents_and_claude_from_target_repo(repo):
    write_file("AGENTS.md", "Convention: use tabs.")
    write_file("CLAUDE.md", "Convention: small PRs.")
    g = r.get_repo_guidelines()
    assert "use tabs" in g and "small PRs" in g
    assert "AGENTS.md" in g and "CLAUDE.md" in g          # labeled by source file


def test_empty_when_no_guidance_files(repo):
    assert r.get_repo_guidelines() == ""


def test_get_arch_context_prefers_repo_guidelines(repo):
    write_file("AGENTS.md", "REPO_MARKER_XYZ")
    # returns the repo guidelines without touching the Chroma fallback
    assert "REPO_MARKER_XYZ" in r.get_arch_context("any query")


def test_guidelines_are_length_capped(repo):
    write_file("AGENTS.md", "x" * 50_000)
    assert len(r.get_repo_guidelines(max_chars=1000)) == 1000


def test_reads_claude_md_from_dot_claude_dir(repo):
    write_file(".claude/CLAUDE.md", "Nested convention ABC")
    g = r.get_repo_guidelines()
    assert "Nested convention ABC" in g and ".claude/CLAUDE.md" in g


def test_identical_content_is_not_duplicated(repo):
    # same content at root and under .claude/ -> included once
    write_file("CLAUDE.md", "SAME BODY")
    write_file(".claude/CLAUDE.md", "SAME BODY")
    assert r.get_repo_guidelines().count("SAME BODY") == 1
