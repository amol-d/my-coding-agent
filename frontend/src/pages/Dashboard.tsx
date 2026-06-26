import {useEffect, useRef, useState} from "react"
import {useParams} from "react-router-dom"
import HITLPanel from "../components/HITLPanel"

type LogEntry = { node: string; summary: string; ts: string }

export default function Dashboard() {
    const {taskId} = useParams<{ taskId: string }>()
    const [log, setLog] = useState<LogEntry[]>([])
    const [hitlEvent, setHitlEvent] = useState<any>(null)
    const [status, setStatus] = useState<"running" | "waiting" | "done" | "error">("running")
    const wsRef = useRef<WebSocket | null>(null)

    useEffect(() => {
        const ws = new WebSocket(`ws://localhost:8000/ws/${taskId}`)
        wsRef.current = ws

        ws.onmessage = (msg) => {
            const data = JSON.parse(msg.data)

            if (data.event === "node_complete") {
                setLog(prev => [...prev, {
                    node: data.node,
                    summary: `${data.node} completed`,
                    ts: new Date().toLocaleTimeString()
                }])
            }

            if (data.event === "hitl_required") {
                setHitlEvent(data)
                setStatus("waiting")
            }

            if (data.event === "error") {
                setStatus("error")
                setLog(prev => [...prev, {
                    node: "error", summary: data.message, ts: new Date().toLocaleTimeString()
                }])
            }
        }

        return () => ws.close()
    }, [taskId])

    const stageIcon: Record<string, string> = {
        coding: "ti-code",
        review: "ti-eye",
        hitl_code: "ti-user-check",
        testing: "ti-flask",
        hitl_tests: "ti-user-check",
        pr_manager: "ti-git-pull-request",
        hitl_deploy: "ti-rocket",
        error: "ti-alert-triangle"
    }

    return (
        <div style={{maxWidth: 720, margin: "0 auto", padding: "2rem 1rem"}}>
            <div style={{
                display: "flex", alignItems: "center",
                gap: 12, marginBottom: "2rem"
            }}>
                <h1 style={{fontSize: 22, fontWeight: 500, margin: 0}}>Pipeline run</h1>
                <span style={{
                    fontSize: 12, padding: "3px 10px", borderRadius: 20,
                    background: status === "waiting" ? "var(--bg-warning)"
                        : status === "error" ? "var(--bg-danger)"
                            : status === "done" ? "var(--bg-success)"
                                : "var(--bg-accent)",
                    color: status === "waiting" ? "var(--text-warning)"
                        : status === "error" ? "var(--text-danger)"
                            : status === "done" ? "var(--text-success)"
                                : "var(--text-accent)"
                }}>
          {status === "running" ? "Running"
              : status === "waiting" ? "Waiting for review"
                  : status === "error" ? "Error"
                      : "Done"}
        </span>
                <span style={{
                    fontSize: 12, color: "var(--text-muted)",
                    fontFamily: "var(--font-mono)", marginLeft: "auto"
                }}>
          {taskId?.slice(0, 8)}
        </span>
            </div>

            <div style={{
                background: "var(--surface-1)", borderRadius: 12,
                border: "0.5px solid var(--border)", padding: "1rem",
                marginBottom: "1rem"
            }}>
                {log.length === 0 && (
                    <div style={{
                        fontSize: 13, color: "var(--text-muted)", textAlign: "center",
                        padding: "1rem 0"
                    }}>
                        Agents starting up...
                    </div>
                )}
                {log.map((entry, i) => (
                    <div key={i} style={{
                        display: "flex", alignItems: "center", gap: 10,
                        padding: "8px 0",
                        borderTop: i > 0 ? "0.5px solid var(--border)" : "none"
                    }}>
                        <i className={`ti ${stageIcon[entry.node] || "ti-circle-check"}`}
                           aria-hidden style={{fontSize: 16, color: "var(--text-secondary)"}}/>
                        <span style={{fontSize: 13, flex: 1}}>{entry.summary}</span>
                        <span style={{
                            fontSize: 11, color: "var(--text-muted)",
                            fontFamily: "var(--font-mono)"
                        }}>{entry.ts}</span>
                    </div>
                ))}
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