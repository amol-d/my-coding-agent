import {useEffect, useRef, useState} from "react"
import {useParams} from "react-router-dom"
import HITLPanel from "../components/HITLPanel"

type StageStatus = "pending" | "active" | "done" | "error"
type StageState = { status: StageStatus; action: string }
type LogEntry = { node: string; summary: string; ts: string }

// Ordered pipeline stages shown in the stepper. HITL gates surface via the
// status badge + panel rather than their own step rows.
const STAGES: {node: string; label: string; icon: string}[] = [
    {node: "ingest",  label: "Ingest documents",   icon: "ti-file-text"},
    {node: "plan",    label: "Plan implementation", icon: "ti-list-check"},
    {node: "coding",  label: "Generate code",       icon: "ti-code"},
    {node: "review",  label: "Review & lint",       icon: "ti-eye"},
    {node: "testing", label: "Write & run tests",   icon: "ti-flask"},
    {node: "commit",  label: "Commit changes",      icon: "ti-git-commit"},
    {node: "pr_manager", label: "Push & open PR",   icon: "ti-git-pull-request"},
    {node: "deploy",  label: "Deploy",              icon: "ti-rocket"},
]

const HITL_TO_STAGE: Record<string, string> = {
    hitl_git_ops: "pr_manager",
    hitl_plan: "plan", hitl_code: "review", hitl_tests: "testing",
    hitl_commit: "commit", hitl_deploy: "deploy",
}

export default function Dashboard() {
    const {taskId} = useParams<{ taskId: string }>()
    const [stages, setStages] = useState<Record<string, StageState>>({})
    const [log, setLog] = useState<LogEntry[]>([])
    const [hitlEvent, setHitlEvent] = useState<any>(null)
    const [status, setStatus] = useState<"running" | "waiting" | "done" | "error">("running")
    const [showLog, setShowLog] = useState(false)
    const [usage, setUsage] = useState<{ tokens: number; cost: number } | null>(null)
    const wsRef = useRef<WebSocket | null>(null)

    const setStage = (node: string, patch: Partial<StageState>) =>
        setStages(prev => ({...prev, [node]: {...(prev[node] || {status: "pending", action: ""}), ...patch}}))

    useEffect(() => {
        const token = localStorage.getItem("token") || ""
        const ws = new WebSocket(`ws://localhost:8000/ws/${taskId}?token=${encodeURIComponent(token)}`)
        wsRef.current = ws

        ws.onmessage = (msg) => {
            const data = JSON.parse(msg.data)
            const now = new Date().toLocaleTimeString()

            switch (data.event) {
                case "stage_started":
                    setStatus("running")
                    setStage(data.node, {status: "active", action: data.action || ""})
                    setLog(prev => [...prev, {node: data.node, summary: data.action || `${data.node} started`, ts: now}])
                    break
                case "stage_progress":
                    setStage(data.node, {status: "active", action: data.action || ""})
                    if (data.action)
                        setLog(prev => [...prev, {node: data.node, summary: data.action, ts: now}])
                    break
                case "node_complete":
                    setStage(data.node, {status: "done", action: data.action || "completed"})
                    setLog(prev => [...prev, {node: data.node, summary: data.action || `${data.node} completed`, ts: now}])
                    break
                case "hitl_required": {
                    setHitlEvent(data)
                    setStatus("waiting")
                    const stg = HITL_TO_STAGE[data.node]
                    if (stg) setStage(stg, {status: "done", action: "awaiting your review"})
                    break
                }
                case "usage":
                    setUsage({tokens: data.run_tokens || 0, cost: data.run_cost_usd || 0})
                    break
                case "pipeline_complete":
                    setStatus("done")
                    setLog(prev => [...prev, {node: "done", summary: "Pipeline finished", ts: now}])
                    break
                case "error": {
                    setStatus("error")
                    if (data.node) setStage(data.node, {status: "error", action: data.message || "error"})
                    setLog(prev => [...prev, {node: data.node || "error", summary: data.message || "error", ts: now}])
                    break
                }
            }
        }

        return () => ws.close()
    }, [taskId])

    const badge = (() => {
        const map = {
            running: {t: "Running", bg: "var(--bg-accent)", c: "var(--text-accent)"},
            waiting: {t: "Waiting for review", bg: "var(--bg-warning)", c: "var(--text-warning)"},
            error:   {t: "Error", bg: "var(--bg-danger)", c: "var(--text-danger)"},
            done:    {t: "Done", bg: "var(--bg-success)", c: "var(--text-success)"},
        } as const
        return map[status]
    })()

    const dot = (s: StageStatus) => {
        if (s === "done")   return {icon: "ti-circle-check-filled", color: "var(--text-success)", spin: false}
        if (s === "active") return {icon: "ti-loader-2",            color: "var(--text-accent)",  spin: true}
        if (s === "error")  return {icon: "ti-alert-triangle-filled", color: "var(--text-danger)", spin: false}
        return {icon: "ti-circle", color: "var(--text-muted)", spin: false}
    }

    return (
        <div style={{maxWidth: 760, margin: "0 auto", padding: "2rem 1rem"}}>
            <div style={{display: "flex", alignItems: "center", gap: 12, marginBottom: "2rem"}}>
                <h1 style={{fontSize: 22, fontWeight: 500, margin: 0}}>Pipeline run</h1>
                <span style={{
                    fontSize: 12, padding: "3px 10px", borderRadius: 20,
                    background: badge.bg, color: badge.c
                }}>{badge.t}</span>
                {usage && (
                    <span title={`${usage.tokens.toLocaleString()} tokens across LLM calls`}
                          style={{
                              fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)",
                              marginLeft: "auto"
                          }}>
                        <i className="ti ti-coin" aria-hidden style={{marginRight: 4}}/>
                        {usage.tokens >= 1000 ? `${(usage.tokens / 1000).toFixed(1)}k` : usage.tokens} tok
                        {" · $"}{usage.cost.toFixed(4)}
                    </span>
                )}
                <span style={{
                    fontSize: 12, color: "var(--text-muted)",
                    fontFamily: "var(--font-mono)", marginLeft: usage ? 12 : "auto"
                }}>{taskId?.slice(0, 8)}</span>
            </div>

            {/* ── STAGE STEPPER ── */}
            <div style={{
                background: "var(--surface-1)", borderRadius: 12,
                border: "0.5px solid var(--border)", padding: "0.5rem 1rem",
                marginBottom: "1rem"
            }}>
                {STAGES.map((s, i) => {
                    const st = stages[s.node]?.status || "pending"
                    const action = stages[s.node]?.action || ""
                    const d = dot(st)
                    return (
                        <div key={s.node} style={{
                            display: "flex", alignItems: "flex-start", gap: 12,
                            padding: "10px 0",
                            borderTop: i > 0 ? "0.5px solid var(--border)" : "none",
                            opacity: st === "pending" ? 0.5 : 1
                        }}>
                            <i className={`ti ${d.icon} ${d.spin ? "spin" : ""}`} aria-hidden
                               style={{fontSize: 18, color: d.color, marginTop: 1}}/>
                            <div style={{flex: 1, minWidth: 0}}>
                                <div style={{fontSize: 13.5, display: "flex", alignItems: "center", gap: 8}}>
                                    <i className={`ti ${s.icon}`} aria-hidden
                                       style={{fontSize: 14, color: "var(--text-secondary)"}}/>
                                    {s.label}
                                </div>
                                {action && st !== "pending" && (
                                    <div style={{
                                        fontSize: 12, color: st === "error" ? "var(--text-danger)" : "var(--text-muted)",
                                        marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"
                                    }}>{action}</div>
                                )}
                            </div>
                        </div>
                    )
                })}
                {Object.keys(stages).length === 0 && (
                    <div style={{fontSize: 13, color: "var(--text-muted)", textAlign: "center", padding: "0.75rem 0"}}>
                        Agents starting up…
                    </div>
                )}
            </div>

            {/* ── ACTIVITY LOG (collapsible) ── */}
            <div style={{marginBottom: "1rem"}}>
                <button onClick={() => setShowLog(v => !v)} style={{fontSize: 12}}>
                    <i className={`ti ${showLog ? "ti-chevron-down" : "ti-chevron-right"}`}
                       aria-hidden style={{marginRight: 6}}/>
                    Activity log ({log.length})
                </button>
                {showLog && (
                    <div style={{
                        marginTop: 8, background: "var(--surface-1)", borderRadius: 10,
                        border: "0.5px solid var(--border)", padding: "0.5rem 0.875rem",
                        maxHeight: 260, overflowY: "auto"
                    }}>
                        {log.map((e, i) => (
                            <div key={i} style={{display: "flex", gap: 10, padding: "4px 0", fontSize: 12}}>
                                <span style={{fontFamily: "var(--font-mono)", color: "var(--text-muted)"}}>{e.ts}</span>
                                <span style={{fontFamily: "var(--font-mono)", color: "var(--text-secondary)"}}>{e.node}</span>
                                <span style={{flex: 1, color: "var(--text-primary)"}}>{e.summary}</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {hitlEvent && status === "waiting" && (
                <HITLPanel
                    taskId={taskId!}
                    event={hitlEvent}
                    onResume={() => {
                        setHitlEvent(null)
                        setStatus("running")
                    }}
                />
            )}
        </div>
    )
}
