import {useState} from "react"
import axios from "axios"

type HITLEvent = {
    node: string
    stage: string
    payload: any
}

type Props = {
    taskId: string
    event: HITLEvent
    onResume: () => void
}

export default function HITLPanel({taskId, event, onResume}: Props) {
    const [feedback, setFeedback] = useState("")
    const [editedCode, setEditedCode] = useState(
        JSON.stringify(event.payload.generated_code || {}, null, 2)
    )
    const [showEdit, setShowEdit] = useState(false)

    const checkpointName = {
        "code_generated": "code_review",
        "review_complete": "code_review",
        "testing_complete": "test_review",
        "pr_created": "deploy_gate"
    }[event.stage] || "code_review"

    const resume = async (action: string) => {
        const body: any = {checkpoint: checkpointName, action, feedback}
        if (action === "edit") body.edited_code = JSON.parse(editedCode)
        await axios.post(`http://localhost:8000/api/resume/${taskId}`, body)
        onResume()
    }

    const stageLabel = {
        code_generated: "Generated code — review before testing",
        review_complete: "Code review complete — approve or revise",
        testing_complete: "Tests ran — approve PR creation",
        pr_created: "PR created — approve deployment"
    }[event.stage] || event.stage

    return (
        <div style={{
            background: "var(--surface-2)",
            border: "0.5px solid var(--border-warning)",
            borderRadius: 12, padding: "1.25rem", marginTop: "1rem"
        }}>
            <div style={{
                display: "flex", alignItems: "center",
                gap: 8, marginBottom: "1rem"
            }}>
                <i className="ti ti-user-check" aria-hidden
                   style={{fontSize: 18, color: "var(--text-warning)"}}/>
                <span style={{fontWeight: 500}}>Review required</span>
                <span style={{
                    fontSize: 12, color: "var(--text-secondary)",
                    marginLeft: "auto"
                }}>
          {stageLabel}
        </span>
            </div>

            {event.stage === "code_generated" && (
                <div style={{marginBottom: "1rem"}}>
                    <div style={{fontSize: 13, color: "var(--text-secondary)", marginBottom: 8}}>
                        Generated files
                    </div>
                    {Object.keys(event.payload.generated_code || {}).map(file => (
                        <div key={file} style={{
                            fontSize: 13, fontFamily: "var(--font-mono)",
                            padding: "4px 8px", background: "var(--surface-1)",
                            borderRadius: "var(--radius)", marginBottom: 4
                        }}>
                            <i className="ti ti-file-code" aria-hidden style={{marginRight: 6}}/>
                            {file}
                        </div>
                    ))}
                </div>
            )}

            {event.stage === "testing_complete" && (
                <div style={{
                    padding: "0.75rem", background: "var(--surface-1)",
                    borderRadius: "var(--radius)", marginBottom: "1rem",
                    borderLeft: `3px solid ${
                        event.payload.test_results?.passed
                            ? "var(--border-success)"
                            : "var(--border-danger)"
                    }`
                }}>
                    <div style={{
                        fontSize: 13, fontWeight: 500, marginBottom: 4,
                        color: event.payload.test_results?.passed
                            ? "var(--text-success)" : "var(--text-danger)"
                    }}>
                        {event.payload.test_results?.passed ? "All tests passed" : "Tests failed"}
                    </div>
                    <pre style={{
                        fontSize: 11, fontFamily: "var(--font-mono)",
                        whiteSpace: "pre-wrap", margin: 0,
                        color: "var(--text-secondary)", maxHeight: 160, overflowY: "auto"
                    }}>
            {event.payload.test_results?.output?.slice(0, 800)}
          </pre>
                </div>
            )}

            {event.stage === "pr_created" && (
                <div style={{marginBottom: "1rem"}}>
                    <a href={event.payload.pr_url} target="_blank" rel="noreferrer"
                       style={{fontSize: 13, color: "var(--text-accent)"}}>
                        <i className="ti ti-git-pull-request" aria-hidden style={{marginRight: 6}}/>
                        {event.payload.pr_url}
                    </a>
                </div>
            )}

            <div style={{marginBottom: "1rem"}}>
                <label style={{
                    fontSize: 13, color: "var(--text-secondary)",
                    display: "block", marginBottom: 6
                }}>
                    Feedback for agent (optional)
                </label>
                <textarea
                    value={feedback}
                    onChange={e => setFeedback(e.target.value)}
                    placeholder="Tell the agent what to fix or improve..."
                    rows={2}
                    style={{width: "100%", resize: "vertical"}}
                />
            </div>

            {showEdit && event.stage === "code_generated" && (
                <div style={{marginBottom: "1rem"}}>
                    <label style={{
                        fontSize: 13, color: "var(--text-secondary)",
                        display: "block", marginBottom: 6
                    }}>
                        Edit generated code (JSON)
                    </label>
                    <textarea
                        value={editedCode}
                        onChange={e => setEditedCode(e.target.value)}
                        rows={10}
                        style={{
                            width: "100%", fontFamily: "var(--font-mono)",
                            fontSize: 12, resize: "vertical"
                        }}
                    />
                </div>
            )}

            <div style={{display: "flex", gap: 8, flexWrap: "wrap"}}>
                <button onClick={() => resume("approved")}
                        style={{
                            background: "var(--bg-success)",
                            color: "var(--text-success)",
                            border: "0.5px solid var(--border-success)"
                        }}>
                    <i className="ti ti-check" aria-hidden style={{marginRight: 6}}/>
                    Approve
                </button>
                <button onClick={() => resume("rejected")}>
                    <i className="ti ti-x" aria-hidden style={{marginRight: 6}}/>
                    Reject — retry
                </button>
                {event.stage === "code_generated" && (
                    <button onClick={() => {
                        setShowEdit(!showEdit)
                    }}>
                        <i className="ti ti-edit" aria-hidden style={{marginRight: 6}}/>
                        {showEdit ? "Hide editor" : "Edit code"}
                    </button>
                )}
                {showEdit && (
                    <button onClick={() => resume("edit")}>
                        <i className="ti ti-device-floppy" aria-hidden style={{marginRight: 6}}/>
                        Save edits and continue
                    </button>
                )}
            </div>
        </div>
    )
}