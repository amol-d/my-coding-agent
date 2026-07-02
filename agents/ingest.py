"""Ingest agent — classify intent and consolidate inputs into a clarified spec.

First it extracts *control directives* from the natural-language instructions
(create a PR? deploy? reuse the current branch? is this a pure git operation?)
so the user's words actually drive the pipeline instead of being turned into
code. Then, for code-change requests, it builds one clear specification from the
instructions + parsed docs/design images + Figma links + RAG arch context.
"""

from dotenv import load_dotenv
load_dotenv()

import json

from arch_rag.retriever import get_arch_context
from events import emit
from llm import get_llm

STAGE = "ingest"


def _extract_directives(raw: str, task_id: str) -> dict:
    """Classify the request and pull out git/deploy control flags from free text.

    Returns keys: intent_type ('code_change'|'git_ops'|'mixed'),
    create_pr, deploy, create_new_branch (each true|false|None where None = not
    mentioned).
    """
    emit(task_id, "stage_progress", action="Understanding your request", node=STAGE)
    prompt = f"""Classify the following developer request and extract control directives.

REQUEST:
{raw}

Definitions:
- "git_ops": the request is ONLY about repository/git operations (e.g. push the
  current branch, open/create a pull request, commit, merge, tag) with NO change
  to application source code.
- "code_change": the request asks to write or modify application code/content.
- "mixed": asks to change code AND perform a git operation (e.g. "update X and open a PR").

Also detect explicit instructions about:
- create_pr: does the user want a pull request opened? (true/false/null if unstated)
- deploy: does the user want a deployment? (true/false/null)
- create_new_branch: false if the user says to use/push the CURRENT branch or not
  create a new branch; true if they want a new branch; null if unstated.
- base_branch: the TARGET branch a PR/merge should go INTO (e.g. "open PR to dev"
  -> "dev"; "merge into main" -> "main"). Return the branch name string, or null
  if the user did not specify a target branch.

Return ONLY a JSON object, no prose, no code fences:
{{"intent_type": "...", "create_pr": true|false|null, "deploy": true|false|null, "create_new_branch": true|false|null, "base_branch": "..."|null}}"""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=300)
    try:
        content = llm.invoke(prompt).content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(content)
    except Exception:
        data = {}

    intent = data.get("intent_type")
    if intent not in ("code_change", "git_ops", "mixed"):
        intent = "code_change"

    def _tri(v):
        return v if isinstance(v, bool) else None

    base = data.get("base_branch")
    base = base.strip() if isinstance(base, str) and base.strip() else None

    return {
        "intent_type": intent,
        "create_pr": _tri(data.get("create_pr")),
        "deploy": _tri(data.get("deploy")),
        "create_new_branch": _tri(data.get("create_new_branch")),
        "base_branch": base,
    }


def _merge_options(directives: dict, ui_opts: dict) -> dict:
    """Natural-language directives override UI toggles when explicitly stated."""
    d_pr, d_dep = directives["create_pr"], directives["deploy"]
    return {
        "create_pr": d_pr if d_pr is not None else bool(ui_opts.get("create_pr")),
        "deploy": d_dep if d_dep is not None else bool(ui_opts.get("deploy")),
    }


def ingest_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    emit(task_id, "stage_started", action="Consolidating inputs", node=STAGE)

    raw = state.get("raw_instructions", "") or ""
    design_inputs = state.get("design_inputs", []) or []
    figma_links = state.get("figma_links", []) or []

    # 1. figure out what the user actually wants and how git should behave
    directives = _extract_directives(raw, task_id)
    options = _merge_options(directives, state.get("options", {}) or {})
    create_new_branch = directives["create_new_branch"]
    if create_new_branch is None:
        create_new_branch = True
    intent_type = directives["intent_type"]

    control = {
        "options": options,
        "intent_type": intent_type,
        "create_new_branch": create_new_branch,
        "base_branch": directives.get("base_branch"),
    }

    # 2. pure git operation → skip codegen; the ops path handles push/PR directly
    if intent_type == "git_ops":
        emit(task_id, "node_complete", node=STAGE,
             action="Git operation — skipping code generation")
        return {**control, "clarified_spec": raw, "current_stage": "spec_ready"}

    # 3. code change / mixed → build a full specification
    doc_sections = []
    for d in design_inputs:
        emit(task_id, "stage_progress",
             action=f"Read {d.get('kind', 'doc')}: {d.get('name', '')}", node=STAGE)
        doc_sections.append(
            f"### {d.get('name', 'document')} ({d.get('kind', 'text')})\n{d.get('text', '')}"
        )
    docs_blob = "\n\n".join(doc_sections) if doc_sections else "None provided."
    figma_blob = "\n".join(f"- {link}" for link in figma_links) if figma_links else "None."

    emit(task_id, "stage_progress", action="Retrieving architecture context", node=STAGE)
    query = raw + "\n" + docs_blob[:2000]
    arch_context = get_arch_context(query)

    prompt = f"""You are a senior product engineer. Turn the following inputs into a single,
clear, self-contained implementation specification. Resolve ambiguity where reasonable,
and explicitly call out open questions that need human input.

RAW INSTRUCTIONS:
{raw}

ATTACHED DOCUMENTS (PRD/BRD/specs/design descriptions):
{docs_blob}

FIGMA / DESIGN LINKS:
{figma_blob}

ARCHITECTURE GUIDELINES:
{arch_context}

Produce a concise but complete spec covering: goal, scope, functional requirements,
UI/UX notes (from any designs), constraints, and open questions. Return plain text."""

    llm = get_llm(task_id=task_id, stage=STAGE, max_tokens=3000)
    response = llm.invoke(prompt)
    clarified_spec = response.content.strip()

    emit(task_id, "node_complete", node=STAGE)
    return {
        **control,
        "clarified_spec": clarified_spec,
        "arch_context": arch_context,
        "current_stage": "spec_ready",
    }
