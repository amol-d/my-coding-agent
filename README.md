# my-coding-agent

# Terminal 1 — backend
python -c "from arch_rag.ingest import ingest_arch_docs; ingest_arch_docs()"  # one-time
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
npm install #for first time
npm run dev
