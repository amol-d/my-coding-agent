"""Parse uploaded design/spec documents into plain text the agents can use.

Handles PRD/BRD PDFs, Word docs, plain text/markdown/code, and Figma-style
design screenshots (interpreted with a vision model). Everything is reduced to
text so the downstream ingest agent can build a single clarified spec.
"""

import base64
import io
from typing import Tuple

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
TEXT_EXTS = (".md", ".txt", ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml")


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "[pypdf not installed — run `poetry install` to read PDFs]"
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages).strip()
    except Exception as e:  # noqa: BLE001 - surface parse errors as text
        return f"[Could not extract PDF text: {e}]"


def _parse_docx(data: bytes) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        return "[python-docx not installed — run `poetry install` to read .docx]"
    try:
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs).strip()
    except Exception as e:  # noqa: BLE001
        return f"[Could not extract .docx text: {e}]"


def _describe_image(filename: str, data: bytes) -> str:
    """Use a vision model to turn a design screenshot into an implementation-ready
    textual description."""
    from llm import get_vision_llm

    ext = filename.rsplit(".", 1)[-1].lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    b64 = base64.b64encode(data).decode("utf-8")

    prompt = [
        {
            "type": "text",
            "text": (
                "This is a UI/UX design screenshot (e.g. exported from Figma). "
                "Describe it precisely for a frontend engineer who must implement it: "
                "layout and structure, components, text/labels, colors, spacing, "
                "states, and any interactions implied. Be concrete and exhaustive."
            ),
        },
        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
    ]
    try:
        response = get_vision_llm().invoke([{"role": "user", "content": prompt}])
        return response.content.strip()
    except Exception as e:  # noqa: BLE001
        return f"[Could not interpret design image {filename}: {e}]"


def parse_document(filename: str, data: bytes) -> Tuple[str, str]:
    """Return (kind, extracted_text) for an uploaded file.

    kind ∈ {"pdf", "docx", "image", "text"} — useful for labeling in the spec.
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return "pdf", _parse_pdf(data)
    if name.endswith(".docx"):
        return "docx", _parse_docx(data)
    if name.endswith(IMAGE_EXTS):
        return "image", _describe_image(filename, data)
    # default: treat as text (covers TEXT_EXTS and anything else)
    return "text", data.decode("utf-8", errors="ignore").strip()
