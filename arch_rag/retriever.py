# arch_rag/retriever.py
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings


def get_arch_context(query: str, k: int = 5) -> str:
    db = Chroma(
        persist_directory="./chroma_db",
        embedding_function=OpenAIEmbeddings()
    )
    docs = db.similarity_search(query, k=k)
    return "\n\n---\n\n".join(d.page_content for d in docs)
