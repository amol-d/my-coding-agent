from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from arch_rag.retriever import get_arch_context
import json

llm = ChatOpenAI(model="gpt-4o", max_tokens=4096)


def coding_agent(state: dict) -> dict:
    # use .get() with fallbacks — state may be partial on resume
    clarified_spec = (
            state.get("clarified_spec")
            or state.get("raw_instructions")
            or ""
    )

    if not clarified_spec:
        return {
            "error": "No task specification found in state",
            "current_stage": "error"
        }

    arch_context = get_arch_context(clarified_spec)

    prompt = f"""You are a senior software engineer. Generate code following 
the architecture guidelines below exactly.

ARCHITECTURE GUIDELINES:
{arch_context}

TASK SPECIFICATION:
{clarified_spec}

Return a JSON object where keys are file paths and values are complete file contents.
Only return the JSON, nothing else."""

    response = llm.invoke(prompt)

    try:
        content = response.content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        code = json.loads(content)
    except Exception:
        code = {"generated_output.txt": response.content}

    return {
        "generated_code": code,
        "arch_context": arch_context,
        "current_stage": "code_generated"
    }
