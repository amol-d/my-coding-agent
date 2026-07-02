"""Central OpenAI model factory.

Keeps model choice configurable via env and wires the StepCallbackHandler so
every LLM call surfaces progress to the UI. Provider stays OpenAI per project
decision; a vision-capable model is used for design screenshots.
"""

import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI

from events import StepCallbackHandler

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")


def get_llm(
    task_id: Optional[str] = None,
    stage: Optional[str] = None,
    max_tokens: int = 4096,
    model: Optional[str] = None,
) -> ChatOpenAI:
    """Return a chat model, attaching a progress callback when task/stage given."""
    callbacks = []
    if task_id and stage:
        callbacks.append(StepCallbackHandler(task_id, stage))
    return ChatOpenAI(
        model=model or DEFAULT_MODEL,
        max_tokens=max_tokens,
        callbacks=callbacks or None,
    )


def get_vision_llm(max_tokens: int = 2048) -> ChatOpenAI:
    """Return a vision-capable chat model for interpreting design screenshots."""
    return ChatOpenAI(model=VISION_MODEL, max_tokens=max_tokens)
