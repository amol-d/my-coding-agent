"""Ingest agent — consolidate all inputs into a single clarified spec.

Takes the raw instructions plus the already-parsed documents/design images and
Figma links (parsing happens upstream in main.py via tools/doc_ingest), pulls
architecture context from the RAG store, and asks the LLM to produce one clear,
self-contained specification for the rest of the pipeline to work from.
"""

from dotenv import load_dotenv
load_dotenv()

from arch_rag.retriever import get_arch_context
from events import emit
from llm import get_llm

STAGE = "ingest"


def ingest_agent(state: dict) -> dict:
    task_id = state.get("task_id", "unknown")
    emit(task_id, "stage_started", action="Consolidating inputs", node=STAGE)

    raw = state.get("raw_instructions", "") or ""
    design_inputs = state.get("design_inputs", []) or []
    figma_links = state.get("figma_links", []) or []

    # design_inputs is a list of {name, kind, text} produced during upload.
    doc_sections = []
    for d in design_inputs:
        emit(task_id, "stage_progress",
             action=f"Read {d.get('kind', 'doc')}: {d.get('name', '')}", node=STAGE)
        doc_sections.append(
            f"### {d.get('name', 'document')} ({d.get('kind', 'text')})\n{d.get('text', '')}"
        )
    docs_blob = "\n\n".join(doc_sections) if doc_sections else "None provided."
    figma_blob = "\n".join(f"- {link}" for link in figma_links) if figma_links else "None."

    # architecture context from RAG
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
        "clarified_spec": clarified_spec,
        "arch_context": arch_context,
        "current_stage": "spec_ready",
    }
