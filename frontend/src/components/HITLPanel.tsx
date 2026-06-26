import { useState } from "react"
import api from "../api/client"
import ReactDiffViewer, { DiffMethod } from "react-diff-viewer-continued"

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

const STAGE_LABELS: Record<string, string> = {
  code_generated:   "Review generated code before testing",
  review_complete:  "Code review complete — approve or request changes",
  testing_complete: "Tests ran — approve PR creation",
  pr_created:       "PR ready — approve deployment",
}

const CHECKPOINT_MAP: Record<string, string> = {
  code_generated:   "code_review",
  review_complete:  "code_review",
  testing_complete: "test_review",
  pr_created:       "deploy_gate",
}

export default function HITLPanel({ taskId, event, onResume }: Props) {
  const { stage, payload } = event

  const checkpointName = CHECKPOINT_MAP[stage] || "code_review"
  const generatedCode: Record<string, string> = payload.generated_code || {}
  const reviewComments: any[] = payload.review_comments || []
  const testResults = payload.test_results || {}

  const fileNames = Object.keys(generatedCode)
  const [selectedFile, setSelectedFile] = useState<string>(fileNames[0] || "")
  const [editedFiles, setEditedFiles] = useState<Record<string, string>>({ ...generatedCode })
  const [isEditing, setIsEditing] = useState(false)
  const [feedback, setFeedback] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const resume = async (action: string) => {
    setSubmitting(true)
    const body: any = { checkpoint: checkpointName, action, feedback }
    if (action === "edit") {
      body.edited_code = editedFiles
    }
    await api.post(`/api/resume/${taskId}`, body)
    onResume()
  }

  const severityColor = (s: string) =>
    s === "blocking" ? "var(--text-danger)" : "var(--text-warning)"

  const severityBg = (s: string) =>
    s === "blocking" ? "var(--bg-danger)" : "var(--bg-warning)"

  return (
    <div style={{
      border: "0.5px solid var(--border-warning)",
      borderRadius: 12,
      overflow: "hidden",
      marginTop: "1rem"
    }}>

      {/* header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "0.875rem 1.25rem",
        borderBottom: "0.5px solid var(--border)",
        background: "var(--bg-warning)"
      }}>
        <i className="ti ti-user-check" aria-hidden
           style={{ fontSize: 18, color: "var(--text-warning)" }}/>
        <span style={{ fontWeight: 500, color: "var(--text-warning)" }}>
          Review required
        </span>
        <span style={{
          marginLeft: "auto", fontSize: 12,
          color: "var(--text-secondary)"
        }}>
          {STAGE_LABELS[stage] || stage}
        </span>
      </div>

      <div style={{ padding: "1.25rem", background: "var(--surface-2)" }}>

        {/* ── CODE DIFF PANEL ── */}
        {stage === "code_generated" && fileNames.length > 0 && (
          <div style={{ marginBottom: "1.25rem" }}>

            {/* file tabs */}
            <div style={{
              display: "flex", gap: 6, flexWrap: "wrap",
              marginBottom: "0.75rem"
            }}>
              {fileNames.map(name => (
                <button
                  key={name}
                  onClick={() => { setSelectedFile(name); setIsEditing(false) }}
                  style={{
                    fontSize: 12,
                    fontFamily: "var(--font-mono)",
                    padding: "4px 10px",
                    borderRadius: "var(--radius)",
                    background: selectedFile === name
                      ? "var(--bg-accent)" : "var(--surface-1)",
                    color: selectedFile === name
                      ? "var(--text-accent)" : "var(--text-secondary)",
                    border: selectedFile === name
                      ? "0.5px solid var(--border-accent)"
                      : "0.5px solid var(--border)"
                  }}
                >
                  <i className="ti ti-file-code" aria-hidden
                     style={{ marginRight: 5, fontSize: 12 }}/>
                  {name}
                </button>
              ))}
            </div>

            {/* diff viewer or editor */}
            {selectedFile && (
              <div style={{
                border: "0.5px solid var(--border)",
                borderRadius: "var(--radius)",
                overflow: "hidden",
                fontSize: 12
              }}>
                {!isEditing ? (
                  <ReactDiffViewer
                    oldValue=""
                    newValue={editedFiles[selectedFile] || ""}
                    splitView={false}
                    compareMethod={DiffMethod.LINES}
                    showDiffOnly={false}
                    leftTitle="original"
                    rightTitle={selectedFile}
                    useDarkTheme={
                      window.matchMedia("(prefers-color-scheme: dark)").matches
                    }
                    styles={{
                      variables: {
                        dark: {
                          diffViewerBackground: "#1e1e1e",
                          addedBackground: "#1a3a1a",
                          addedColor: "#4ec94e",
                          wordAddedBackground: "#1a5c1a",
                        },
                        light: {
                          diffViewerBackground: "#fafafa",
                          addedBackground: "#eaffea",
                          addedColor: "#1a7a1a",
                          wordAddedBackground: "#c6f5c6",
                        }
                      },
                      contentText: {
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        lineHeight: "1.6"
                      }
                    }}
                  />
                ) : (
                  <textarea
                    value={editedFiles[selectedFile] || ""}
                    onChange={e => setEditedFiles(prev => ({
                      ...prev,
                      [selectedFile]: e.target.value
                    }))}
                    rows={20}
                    style={{
                      width: "100%",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      padding: "0.75rem",
                      border: "none",
                      resize: "vertical",
                      background: "var(--surface-1)",
                      color: "var(--text-primary)"
                    }}
                  />
                )}
              </div>
            )}

            {/* toggle edit mode */}
            <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
              <button
                onClick={() => setIsEditing(prev => !prev)}
                style={{ fontSize: 12 }}
              >
                <i className={`ti ${isEditing ? "ti-eye" : "ti-edit"}`}
                   aria-hidden style={{ marginRight: 5 }}/>
                {isEditing ? "Back to diff view" : "Edit this file"}
              </button>
              {isEditing && (
                <span style={{ fontSize: 12, color: "var(--text-muted)",
                               alignSelf: "center" }}>
                  editing {selectedFile}
                </span>
              )}
            </div>
          </div>
        )}

        {/* ── REVIEW COMMENTS ── */}
        {reviewComments.length > 0 && (
          <div style={{ marginBottom: "1.25rem" }}>
            <div style={{
              fontSize: 13, fontWeight: 500, marginBottom: 8,
              color: "var(--text-secondary)"
            }}>
              Review comments
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {reviewComments.map((c, i) => (
                <div key={i} style={{
                  padding: "0.6rem 0.875rem",
                  borderRadius: "var(--radius)",
                  background: severityBg(c.severity),
                  borderLeft: `3px solid ${severityColor(c.severity)}`
                }}>
                  <div style={{
                    display: "flex", alignItems: "center",
                    gap: 8, marginBottom: 3
                  }}>
                    <span style={{
                      fontSize: 11, fontWeight: 500,
                      fontFamily: "var(--font-mono)",
                      color: severityColor(c.severity)
                    }}>
                      {c.severity?.toUpperCase()}
                    </span>
                    <span style={{
                      fontSize: 11,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-secondary)"
                    }}>
                      {c.file}{c.line ? `:${c.line}` : ""}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, color: "var(--text-primary)" }}>
                    {c.comment}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── TEST RESULTS ── */}
        {stage === "testing_complete" && (
          <div style={{ marginBottom: "1.25rem" }}>
            <div style={{
              padding: "0.875rem",
              borderRadius: "var(--radius)",
              background: testResults.passed
                ? "var(--bg-success)" : "var(--bg-danger)",
              borderLeft: `3px solid ${testResults.passed
                ? "var(--border-success)" : "var(--border-danger)"}`
            }}>
              <div style={{
                fontSize: 13, fontWeight: 500, marginBottom: 6,
                color: testResults.passed
                  ? "var(--text-success)" : "var(--text-danger)"
              }}>
                {testResults.passed ? "✅ All tests passed" : "❌ Tests failed"}
              </div>
              <pre style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                whiteSpace: "pre-wrap",
                margin: 0,
                color: "var(--text-secondary)",
                maxHeight: 200,
                overflowY: "auto"
              }}>
                {testResults.output?.slice(0, 1500)}
              </pre>
            </div>
          </div>
        )}

        {/* ── PR LINK ── */}
        {stage === "pr_created" && payload.pr_url && (
          <div style={{ marginBottom: "1.25rem" }}>
            <a
              href={payload.pr_url}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                fontSize: 13, color: "var(--text-accent)",
                padding: "0.6rem 0.875rem",
                border: "0.5px solid var(--border-accent)",
                borderRadius: "var(--radius)",
                background: "var(--bg-accent)",
                textDecoration: "none"
              }}
            >
              <i className="ti ti-git-pull-request" aria-hidden
                 style={{ fontSize: 16 }}/>
              {payload.pr_url}
              <i className="ti ti-external-link" aria-hidden
                 style={{ fontSize: 13 }}/>
            </a>
          </div>
        )}

        {/* ── FEEDBACK ── */}
        <div style={{ marginBottom: "1rem" }}>
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
            style={{ width: "100%", resize: "vertical" }}
          />
        </div>

        {/* ── ACTIONS ── */}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => resume("approved")}
            disabled={submitting}
            style={{
              background: "var(--bg-success)",
              color: "var(--text-success)",
              border: "0.5px solid var(--border-success)"
            }}
          >
            <i className="ti ti-check" aria-hidden style={{ marginRight: 6 }}/>
            Approve
          </button>

          <button
            onClick={() => resume("rejected")}
            disabled={submitting}
            style={{
              background: "var(--bg-danger)",
              color: "var(--text-danger)",
              border: "0.5px solid var(--border-danger)"
            }}
          >
            <i className="ti ti-refresh" aria-hidden style={{ marginRight: 6 }}/>
            Reject — retry
          </button>

          {stage === "code_generated" && (
            <button
              onClick={() => resume("edit")}
              disabled={submitting || !isEditing}
              style={{
                background: "var(--bg-accent)",
                color: "var(--text-accent)",
                border: "0.5px solid var(--border-accent)",
                opacity: isEditing ? 1 : 0.4
              }}
            >
              <i className="ti ti-device-floppy" aria-hidden
                 style={{ marginRight: 6 }}/>
              Save edits and continue
            </button>
          )}

          {stage === "testing_complete" && !testResults.passed && (
            <button
              onClick={() => resume("override")}
              disabled={submitting}
            >
              <i className="ti ti-alert-triangle" aria-hidden
                 style={{ marginRight: 6 }}/>
              Override — create PR anyway
            </button>
          )}
        </div>

        {submitting && (
          <div style={{
            marginTop: 12, fontSize: 13,
            color: "var(--text-muted)"
          }}>
            <i className="ti ti-loader" aria-hidden style={{ marginRight: 6 }}/>
            Resuming pipeline...
          </div>
        )}
      </div>
    </div>
  )
}