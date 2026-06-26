import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import api from "../api/client"

type Run = {
  task_id: string
  instructions: string
  status: "running" | "waiting" | "complete" | "error"
  outcome: string | null
  pr_url: string | null
  error: string | null
  created_at: string
  updated_at: string
  file_names: string[]
}

const STATUS_STYLE: Record<string, { bg: string; color: string; border: string; icon: string }> = {
  running:  { bg: "var(--bg-accent)",   color: "var(--text-accent)",   border: "var(--border-accent)",   icon: "ti-loader" },
  waiting:  { bg: "var(--bg-warning)",  color: "var(--text-warning)",  border: "var(--border-warning)",  icon: "ti-user-check" },
  complete: { bg: "var(--bg-success)",  color: "var(--text-success)",  border: "var(--border-success)",  icon: "ti-check" },
  error:    { bg: "var(--bg-danger)",   color: "var(--text-danger)",   border: "var(--border-danger)",   icon: "ti-alert-circle" },
}

export default function RunHistory() {
  const [runs, setRuns]       = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    api.get("/api/runs").then(({ data }) => {
      setRuns(data.runs)
      setLoading(false)
    })
  }, [])

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit"
    })

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1rem" }}>
      <div style={{ display: "flex", alignItems: "center",
                    gap: 12, marginBottom: "2rem" }}>
        <h1 style={{ fontSize: 22, fontWeight: 500, margin: 0 }}>Run history</h1>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          {runs.length} run{runs.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => navigate("/intake")}
          style={{
            marginLeft: "auto", fontSize: 13,
            background: "var(--bg-accent)",
            color: "var(--text-accent)",
            border: "0.5px solid var(--border-accent)"
          }}
        >
          <i className="ti ti-plus" aria-hidden style={{ marginRight: 6 }}/>
          New run
        </button>
      </div>

      {loading && (
        <div style={{ fontSize: 13, color: "var(--text-muted)",
                      textAlign: "center", padding: "3rem 0" }}>
          Loading...
        </div>
      )}

      {!loading && runs.length === 0 && (
        <div style={{
          textAlign: "center", padding: "3rem",
          color: "var(--text-muted)", fontSize: 13,
          background: "var(--surface-2)",
          border: "0.5px solid var(--border)", borderRadius: 12
        }}>
          <i className="ti ti-history" aria-hidden
             style={{ fontSize: 32, display: "block", marginBottom: 8 }}/>
          No runs yet — start your first task
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {runs.map(run => {
          const s = STATUS_STYLE[run.status] || STATUS_STYLE.error
          return (
            <div
              key={run.task_id}
              style={{
                background: "var(--surface-2)",
                border: "0.5px solid var(--border)",
                borderRadius: 12, padding: "1rem 1.25rem",
                cursor: "pointer",
                transition: "border-color 0.15s"
              }}
              onClick={() => navigate(`/dashboard/${run.task_id}`)}
              onMouseEnter={e =>
                (e.currentTarget.style.borderColor = "var(--border-strong)")}
              onMouseLeave={e =>
                (e.currentTarget.style.borderColor = "var(--border)")}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 500,
                                marginBottom: 4, color: "var(--text-primary)" }}>
                    {run.instructions.slice(0, 100)}
                    {run.instructions.length > 100 ? "..." : ""}
                  </div>

                  <div style={{ display: "flex", gap: 8,
                                flexWrap: "wrap", alignItems: "center" }}>
                    {/* status badge */}
                    <span style={{
                      fontSize: 11, padding: "2px 8px",
                      borderRadius: 20, fontWeight: 500,
                      background: s.bg, color: s.color, border: `0.5px solid ${s.border}`
                    }}>
                      <i className={`ti ${s.icon}`} aria-hidden
                         style={{ marginRight: 4, fontSize: 11 }}/>
                      {run.status}
                    </span>

                    {/* pr link */}
                    {run.pr_url && (
                      
                      <a  href={run.pr_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={e => e.stopPropagation()}
                        style={{
                          fontSize: 11, color: "var(--text-accent)",
                          display: "flex", alignItems: "center", gap: 4
                        }}
                      >
                        <i className="ti ti-git-pull-request" aria-hidden
                           style={{ fontSize: 12 }}/>
                        View PR
                      </a>
                    )}

                    {/* error snippet */}
                    {run.error && (
                      <span style={{ fontSize: 11, color: "var(--text-danger)",
                                     fontFamily: "var(--font-mono)" }}>
                        {run.error.slice(0, 60)}
                      </span>
                    )}

                    {/* attached files */}
                    {run.file_names.map(name => (
                      <span key={name} style={{
                        fontSize: 11, padding: "2px 6px",
                        borderRadius: "var(--radius)",
                        background: "var(--surface-1)",
                        color: "var(--text-muted)",
                        border: "0.5px solid var(--border)",
                        fontFamily: "var(--font-mono)"
                      }}>
                        <i className="ti ti-file" aria-hidden
                           style={{ marginRight: 3, fontSize: 10 }}/>
                        {name}
                      </span>
                    ))}
                  </div>
                </div>

                <div style={{ fontSize: 12, color: "var(--text-muted)",
                              whiteSpace: "nowrap", marginTop: 2 }}>
                  {fmtDate(run.created_at)}
                </div>
              </div>

              <div style={{
                marginTop: 8, fontSize: 11,
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)"
              }}>
                {run.task_id.slice(0, 8)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}