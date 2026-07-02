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

# Resilience defaults. The OpenAI client retries transient failures (429 rate
# limits — honoring Retry-After — plus timeouts, connection errors and 5xx) with
# exponential backoff + jitter, so a blip doesn't kill a run. The timeout bounds
# a single request so a hung call can't stall the pipeline indefinitely.
REQUEST_TIMEOUT = float(os.environ.get("OPENAI_TIMEOUT", "90"))
MAX_RETRIES = int(os.environ.get("OPENAI_MAX_RETRIES", "5"))


def get_llm(
    task_id: Optional[str] = None,
    stage: Optional[str] = None,
    max_tokens: int = 4096,
    model: Optional[str] = None,
) -> ChatOpenAI:
    """Return a chat model, attaching a progress/usage callback when task/stage given."""
    resolved = model or DEFAULT_MODEL
    callbacks = []
    if task_id and stage:
        callbacks.append(StepCallbackHandler(task_id, stage, model=resolved))
    return ChatOpenAI(
        model=resolved,
        max_tokens=max_tokens,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
        callbacks=callbacks or None,
    )


def get_vision_llm(max_tokens: int = 2048) -> ChatOpenAI:
    """Return a vision-capable chat model for interpreting design screenshots."""
    return ChatOpenAI(
        model=VISION_MODEL,
        max_tokens=max_tokens,
        timeout=REQUEST_TIMEOUT,
        max_retries=MAX_RETRIES,
    )
