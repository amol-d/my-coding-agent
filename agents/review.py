from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
import json

llm = ChatOpenAI(model="gpt-4o", max_tokens=2048)


def review_agent(state: dict) -> dict:
    generated_code = state.get("generated_code", {})
    arch_context = state.get("arch_context", "")

    if not generated_code:
        return {
            "review_comments": [],
            "current_stage": "review_complete"
        }

    code_str = json.dumps(generated_code, indent=2)

    prompt = f"""Review the following code. Check for:
- Correctness and logic errors
- Security vulnerabilities
- Adherence to clean code principles
- Consistency with the architecture context provided

ARCHITECTURE CONTEXT:
{arch_context}

CODE TO REVIEW:
{code_str}

Return a JSON array of comments. Each item must have exactly this shape:
{{"file": "filename", "line": null, "severity": "blocking" or "suggestion", "comment": "description"}}
Only return the JSON array, nothing else. No markdown fences."""

    response = llm.invoke(prompt)

    try:
        content = response.content.strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        comments = json.loads(content)
        if not isinstance(comments, list):
            comments = [{"file": "general", "line": None,
                         "severity": "suggestion", "comment": str(comments)}]
    except Exception:
        comments = [{"file": "general", "line": None,
                     "severity": "suggestion", "comment": response.content}]

    return {
        "review_comments": comments,
        "current_stage": "review_complete"
    }
