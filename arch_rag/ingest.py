from dotenv import load_dotenv

load_dotenv()

from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import MarkdownTextSplitter
import glob


def ingest_arch_docs(docs_folder: str = "./arch_docs"):
    splitter = MarkdownTextSplitter(chunk_size=800, chunk_overlap=100)
    docs = []
    for path in glob.glob(f"{docs_folder}/**/*.md", recursive=True):
        with open(path) as f:
            text = f.read().strip()
        if not text:
            print(f"Skipping empty file: {path}")
            continue
        docs += splitter.create_documents([text], metadatas=[{"source": path}])

    if not docs:
        print("No documents found. Add .md files to ./arch_docs/ and retry.")
        return

    print(f"Embedding {len(docs)} chunks...")
    db = Chroma.from_documents(
        docs,
        OpenAIEmbeddings(),
        persist_directory="./chroma_db"
    )
    db.persist()
    print(f"Done. Ingested {len(docs)} chunks from {docs_folder}")
