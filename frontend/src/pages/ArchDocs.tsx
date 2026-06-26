import { useEffect, useState, useRef } from "react"
import api from "../api/client"

type Doc = { name: string; size: number; modified: number }

export default function ArchDocs() {
  const [docs, setDocs]           = useState<Doc[]>([])
  const [uploading, setUploading] = useState(false)
  const [indexing, setIndexing]   = useState(false)
  const [message, setMessage]     = useState<{ text: string; ok: boolean } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    const { data } = await api.get("/api/arch-docs")
    setDocs(data.docs)
  }

  useEffect(() => { load() }, [])

  const flash = (text: string, ok = true) => {
    setMessage({ text, ok })
    setTimeout(() => setMessage(null), 3000)
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    setUploading(true)
    const form = new FormData()
    Array.from(files).forEach(f => form.append("files", f))
    try {
      const { data } = await api.post("/api/arch-docs/upload", form)
      flash(`Uploaded ${data.saved.length} file(s)`)
      await load()
    } catch {
      flash("Upload failed", false)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete ${name}?`)) return
    await api.delete(`/api/arch-docs/${encodeURIComponent(name)}`)
    flash(`Deleted ${name}`)
    await load()
  }

  const handleReindex = async () => {
    setIndexing(true)
    try {
      await api.post("/api/arch-docs/reindex")
      flash("Vector index rebuilt successfully")
    } catch {
      flash("Reindex failed", false)
    } finally {
      setIndexing(false)
    }
  }

  const fmtSize = (bytes: number) =>
    bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`

  const fmtDate = (ts: number) =>
    new Date(ts * 1000).toLocaleDateString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
    })

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
      <div style={{ display: "flex", alignItems: "center",
                    gap: 12, marginBottom: "2rem" }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, margin: 0 }}>
          Architecture docs
        </h1>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          {docs.length} file{docs.length !== 1 ? "s" : ""}
        </span>
      </div>

      {message && (
        <div style={{
          marginBottom: "1rem", fontSize: 13,
          padding: "0.6rem 0.875rem",
          borderRadius: "var(--radius)",
          background: message.ok ? "var(--bg-success)" : "var(--bg-danger)",
          color: message.ok ? "var(--text-success)" : "var(--text-danger)",
          border: `0.5px solid ${message.ok
            ? "var(--border-success)" : "var(--border-danger)"}`
        }}>
          <i className={`ti ${message.ok ? "ti-check" : "ti-alert-circle"}`}
             aria-hidden style={{ marginRight: 6 }}/>
          {message.text}
        </div>
      )}

      {/* upload + reindex row */}
      <div style={{
        display: "flex", gap: 10, marginBottom: "1.5rem",
        padding: "1rem 1.25rem",
        background: "var(--surface-2)",
        border: "0.5px solid var(--border)",
        borderRadius: 12
      }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 13, color: "var(--text-secondary)",
                          display: "block", marginBottom: 6 }}>
            Upload .md files
          </label>
          <input
            ref={fileRef}
            type="file"
            accept=".md"
            multiple
            onChange={handleUpload}
            disabled={uploading}
          />
        </div>
        <div style={{ display: "flex", alignItems: "flex-end" }}>
          <button
            onClick={handleReindex}
            disabled={indexing || docs.length === 0}
            style={{
              background: "var(--bg-accent)",
              color: "var(--text-accent)",
              border: "0.5px solid var(--border-accent)"
            }}
          >
            <i className="ti ti-refresh" aria-hidden style={{ marginRight: 6 }}/>
            {indexing ? "Indexing..." : "Re-index"}
          </button>
        </div>
      </div>

      {/* doc list */}
      <div style={{
        background: "var(--surface-2)",
        border: "0.5px solid var(--border)",
        borderRadius: 12, overflow: "hidden"
      }}>
        {docs.length === 0 ? (
          <div style={{
            padding: "3rem", textAlign: "center",
            color: "var(--text-muted)", fontSize: 13
          }}>
            <i className="ti ti-file-off" aria-hidden
               style={{ fontSize: 32, display: "block", marginBottom: 8 }}/>
            No docs yet — upload some .md files above
          </div>
        ) : (
          docs.map((doc, i) => (
            <div key={doc.name} style={{
              display: "flex", alignItems: "center",
              gap: 12, padding: "0.75rem 1.25rem",
              borderTop: i > 0 ? "0.5px solid var(--border)" : "none"
            }}>
              <i className="ti ti-markdown" aria-hidden
                 style={{ fontSize: 18, color: "var(--text-secondary)" }}/>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontFamily: "var(--font-mono)" }}>
                  {doc.name}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
                  {fmtSize(doc.size)} · updated {fmtDate(doc.modified)}
                </div>
              </div>
              <button
                onClick={() => handleDelete(doc.name)}
                style={{
                  padding: "4px 10px", fontSize: 12,
                  color: "var(--text-danger)",
                  background: "var(--bg-danger)",
                  border: "0.5px solid var(--border-danger)"
                }}
              >
                <i className="ti ti-trash" aria-hidden style={{ marginRight: 4 }}/>
                Delete
              </button>
            </div>
          ))
        )}
      </div>

      <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: "1rem" }}>
        After uploading new files, click Re-index to rebuild the vector store
        so the coding agent picks up the changes.
      </p>
    </div>
  )
}