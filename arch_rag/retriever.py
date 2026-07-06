# arch_rag/retriever.py
"""Architecture / convention context for the agents.

Primary source: the TARGET repo's own AGENTS.md / CLAUDE.md — co-located with the
code and maintained by its owners, so it's always current (this is how Codex and
Claude Code source conventions). Falls back to semantic retrieval over ./arch_docs
(Chroma) only when the target repo ships no guidance files, so a large external
docs corpus is still supported without being required.
"""

import os

from tools.local_repo import read_file

# Files, in order, a repo uses to describe its conventions to coding agents.
# CLAUDE.md conventionally lives at the repo root or under .claude/.
GUIDELINE_FILES = ("AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md", ".claude/AGENTS.md")
MAX_GUIDELINE_CHARS = int(os.environ.get("ARCH_GUIDELINE_MAX_CHARS", "12000"))


def get_repo_guidelines(max_chars: int = MAX_GUIDELINE_CHARS) -> str:
    """Read the target repo's agent-guidance files. Empty string if none exist.

    Reads through tools.local_repo, so it honors the active repo (the per-run
    worktree during coding, the main checkout otherwise) and the path-safety guard.
    Identical content found at more than one location is included only once.
    """
    sections = []
    seen: set[str] = set()
    for name in GUIDELINE_FILES:
        content = read_file(name)
        if not content or not content.strip():
            continue
        body = content.strip()
        if body in seen:                     # e.g. root CLAUDE.md == .claude/CLAUDE.md
            continue
        seen.add(body)
        sections.append(f"# ===== {name} (from the target repository) =====\n{body}")
    return "\n\n".join(sections)[:max_chars]


def get_arch_context(query: str, k: int = 5) -> str:
    """Convention/architecture context for the agents: the target repo's own
    guidance files first; else semantic retrieval over ./arch_docs, if that vector
    store was built. Returns "" when neither is available."""
    guidelines = get_repo_guidelines()
    if guidelines:
        return guidelines

    # Fallback: optional Chroma RAG over ./arch_docs (legacy / large external corpus).
    # Imported lazily so the common path pulls in neither Chroma nor embeddings.
    try:
        from langchain_community.vectorstores import Chroma
        from langchain_openai import OpenAIEmbeddings
        db = Chroma(persist_directory="./chroma_db", embedding_function=OpenAIEmbeddings())
        docs = db.similarity_search(query, k=k)
        return "\n\n---\n\n".join(d.page_content for d in docs)
    except Exception:  # noqa: BLE001 - RAG is optional; never fail a run over it
        return ""
