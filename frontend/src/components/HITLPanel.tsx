import {useState} from "react"
import api from "../api/client"
import ReactDiffViewer, {DiffMethod} from "react-diff-viewer-continued"

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

// Keyed by the interrupt node name (event.node), which the backend sets
// reliably from snapshot.next — current_stage collides across checkpoints.
const NODE_LABELS: Record<string, string> = {
    hitl_git_ops: "Confirm the requested git operation",
    hitl_plan: "Review the implementation plan before coding",
    hitl_code: "Review generated code before testing",
    hitl_tests: "Tests ran — approve to proceed",
    hitl_commit: "Approve committing the changes (no push)",
    hitl_deploy: "Approve deployment",
}

const CHECKPOINT_MAP: Record<string, string> = {
    hitl_git_ops: "git_ops",
    hitl_plan: "plan",
    hitl_code: "code_review",
    hitl_tests: "test_review",
    hitl_commit: "commit",
    hitl_deploy: "deploy_gate",
}

export default function HITLPanel({taskId, event, onResume}: Props) {
    const {node, payload} = event

    const checkpointName = CHECKPOINT_MAP[node] || "code_review"
    const generatedCode: Record<string, string> = payload.generated_code || {}
    const originalCode: Record<string, string> = payload.original_code || {}
    const reviewComments: any[] = payload.review_comments || []
    const lintOutput: Record<string, string> = payload.lint_output || {}
    const testResults = payload.test_results || {}
    const implementationPlan: string = payload.implementation_plan || ""
    const writtenFiles: string[] = payload.written_files || []
    const branchName: string = payload.branch_name || ""

    // test-result presentation (status added by the backend testing agent)
    const testStatus: string = testResults.status
    const testsRan = testResults.ran !== false && (testStatus === "passed" || testStatus === "failed")
    const testTone = testStatus === "failed" ? "danger" : testsRan ? "success" : "warning"
    const testHeadline =
        testStatus === "passed" ? "✅ All tests passed"
        : testStatus === "failed" ? "❌ Tests failed"
        : testStatus === "no_tests" ? "➖ No tests were collected"
        : testStatus === "runner_unavailable" ? "⚠️ Test runner unavailable — tests not run"
        : testResults.passed ? "✅ All tests passed"
        : "⚠️ Tests skipped — no runner for the generated tests"

    const fileNames = Object.keys(generatedCode)
    const [selectedFile, setSelectedFile] = useState<string>(fileNames[0] || "")
    const [editedFiles, setEditedFiles] = useState<Record<string, string>>({...generatedCode})
    const [isEditing, setIsEditing] = useState(false)
    const [feedback, setFeedback] = useState("")
    const [submitting, setSubmitting] = useState(false)

    const isDarkMode = window.matchMedia("(prefers-color-scheme: dark)").matches

    const resume = async (action: string) => {
        setSubmitting(true)
        const body: any = {checkpoint: checkpointName, action, feedback}
        if (action === "edit") body.edited_code = editedFiles
        await api.post(`/api/resume/${taskId}`, body)
        onResume()
    }

    const severityColor = (s: string) =>
        s === "blocking" ? "var(--text-danger)" : "var(--text-warning)"

    const severityBg = (s: string) =>
        s === "blocking" ? "var(--bg-danger)" : "var(--bg-warning)"

    // files that are new (no original) vs modified
    const isNewFile = (name: string) => !originalCode[name]

    return (
        <div style={{
            border: "0.5px solid var(--border-warning)",
            borderRadius: 12,
            overflow: "hidden",
            marginTop: "1rem"
        }}>

            {/* ── HEADER ── */}
            <div style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "0.875rem 1.25rem",
                borderBottom: "0.5px solid var(--border)",
                background: "var(--bg-warning)"
            }}>
                <i className="ti ti-user-check" aria-hidden
                   style={{fontSize: 18, color: "var(--text-warning)"}}/>
                <span style={{fontWeight: 500, color: "var(--text-warning)"}}>
          Review required
        </span>
                <span style={{marginLeft: "auto", fontSize: 12, color: "var(--text-secondary)"}}>
          {NODE_LABELS[node] || node}
        </span>
            </div>

            <div style={{padding: "1.25rem", background: "var(--surface-2)"}}>

                {/* ── GIT OPERATION ── */}
                {node === "hitl_git_ops" && (
                    <div style={{marginBottom: "1.25rem"}}>
                        <div style={{fontSize: 13, fontWeight: 500, marginBottom: 8, color: "var(--text-secondary)"}}>
                            The agent understood this as a git operation (no code will be generated)
                        </div>
                        <div style={{
                            padding: "0.875rem", borderRadius: "var(--radius)",
                            background: "var(--surface-1)", border: "0.5px solid var(--border)",
                            fontSize: 13, lineHeight: 1.7
                        }}>
                            <div>
                                <i className="ti ti-git-branch" aria-hidden style={{marginRight: 6}}/>
                                Push branch:{" "}
                                <span style={{fontFamily: "var(--font-mono)"}}>
                                    {payload.branch_name || "(current branch)"}
                                </span>
                            </div>
                            <div>
                                <i className="ti ti-git-pull-request" aria-hidden style={{marginRight: 6}}/>
                                Open pull request: <strong>{payload.create_pr ? "yes" : "no"}</strong>
                            </div>
                            {payload.create_pr && (
                                <div>
                                    <i className="ti ti-target" aria-hidden style={{marginRight: 6}}/>
                                    Target (base) branch:{" "}
                                    <span style={{fontFamily: "var(--font-mono)"}}>
                                        {payload.base_branch || "(default branch)"}
                                    </span>
                                </div>
                            )}
                            <div>
                                <i className="ti ti-rocket" aria-hidden style={{marginRight: 6}}/>
                                Deploy: <strong>{payload.deploy ? "yes" : "no"}</strong>
                            </div>
                        </div>
                        <div style={{fontSize: 12, color: "var(--text-muted)", marginTop: 6}}>
                            Approve to run it, or Abort to cancel.
                        </div>
                    </div>
                )}

                {/* ── IMPLEMENTATION PLAN ── */}
                {node === "hitl_plan" && (
                    <div style={{marginBottom: "1.25rem"}}>
                        <div style={{fontSize: 13, fontWeight: 500, marginBottom: 8, color: "var(--text-secondary)"}}>
                            Implementation plan
                        </div>
                        <pre style={{
                            fontSize: 12.5, whiteSpace: "pre-wrap", margin: 0,
                            padding: "0.875rem", borderRadius: "var(--radius)",
                            background: "var(--surface-1)", border: "0.5px solid var(--border)",
                            color: "var(--text-primary)", maxHeight: 360, overflowY: "auto",
                            lineHeight: 1.6
                        }}>
              {implementationPlan || "No plan produced."}
            </pre>
                        <div style={{fontSize: 12, color: "var(--text-muted)", marginTop: 6}}>
                            Approve to start coding, or use the feedback box below and choose
                            “Request changes” to revise the plan.
                        </div>
                    </div>
                )}

                {/* ── COMMIT GATE ── */}
                {node === "hitl_commit" && (
                    <div style={{marginBottom: "1.25rem"}}>
                        <div style={{fontSize: 13, fontWeight: 500, marginBottom: 8, color: "var(--text-secondary)"}}>
                            Ready to commit to branch{" "}
                            <span style={{fontFamily: "var(--font-mono)"}}>{branchName}</span>
                            {" "}(will not push)
                        </div>
                        <div style={{
                            padding: "0.875rem", borderRadius: "var(--radius)",
                            background: "var(--surface-1)", border: "0.5px solid var(--border)"
                        }}>
                            {writtenFiles.length > 0 ? writtenFiles.map(f => (
                                <div key={f} style={{
                                    fontSize: 12, fontFamily: "var(--font-mono)",
                                    color: "var(--text-secondary)"
                                }}>
                                    <i className="ti ti-file-code" aria-hidden style={{marginRight: 5}}/>
                                    {f}
                                </div>
                            )) : <span style={{fontSize: 12, color: "var(--text-muted)"}}>No files listed.</span>}
                        </div>
                    </div>
                )}

                {/* ── CODE DIFF PANEL ── */}
                {node === "hitl_code" && fileNames.length > 0 && (
                    <div style={{marginBottom: "1.25rem"}}>

                        {/* file tabs */}
                        <div style={{display: "flex", gap: 6, flexWrap: "wrap", marginBottom: "0.75rem"}}>
                            {fileNames.map(name => (
                                <button
                                    key={name}
                                    onClick={() => {
                                        setSelectedFile(name);
                                        setIsEditing(false)
                                    }}
                                    style={{
                                        fontSize: 12,
                                        fontFamily: "var(--font-mono)",
                                        padding: "4px 10px",
                                        borderRadius: "var(--radius)",
                                        background: selectedFile === name ? "var(--bg-accent)" : "var(--surface-1)",
                                        color: selectedFile === name ? "var(--text-accent)" : "var(--text-secondary)",
                                        border: selectedFile === name
                                            ? "0.5px solid var(--border-accent)"
                                            : "0.5px solid var(--border)"
                                    }}
                                >
                                    <i className="ti ti-file-code" aria-hidden style={{marginRight: 5, fontSize: 12}}/>
                                    {name}
                                    {/* new vs modified badge */}
                                    <span style={{
                                        marginLeft: 6, fontSize: 10, padding: "1px 5px",
                                        borderRadius: 10,
                                        background: isNewFile(name) ? "var(--bg-success)" : "var(--bg-warning)",
                                        color: isNewFile(name) ? "var(--text-success)" : "var(--text-warning)",
                                    }}>
                    {isNewFile(name) ? "new" : "modified"}
                  </span>
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
                                        oldValue={originalCode[selectedFile] || ""}
                                        newValue={editedFiles[selectedFile] || ""}
                                        splitView={!isNewFile(selectedFile)}
                                        compareMethod={DiffMethod.LINES}
                                        showDiffOnly={false}
                                        leftTitle={
                                            isNewFile(selectedFile)
                                                ? undefined
                                                : `${selectedFile} (original)`
                                        }
                                        rightTitle={
                                            isNewFile(selectedFile)
                                                ? `${selectedFile} (new file)`
                                                : `${selectedFile} (modified)`
                                        }
                                        useDarkTheme={isDarkMode}
                                        styles={{
                                            variables: {
                                                dark: {
                                                    diffViewerBackground: "#1e1e1e",
                                                    addedBackground: "#1a3a1a",
                                                    removedBackground: "#3a1a1a",
                                                    addedColor: "#4ec94e",
                                                    removedColor: "#e05c5c",
                                                    wordAddedBackground: "#1a5c1a",
                                                    wordRemovedBackground: "#5c1a1a",
                                                },
                                                light: {
                                                    diffViewerBackground: "#fafafa",
                                                    addedBackground: "#eaffea",
                                                    removedBackground: "#ffeaea",
                                                    addedColor: "#1a7a1a",
                                                    removedColor: "#7a1a1a",
                                                    wordAddedBackground: "#c6f5c6",
                                                    wordRemovedBackground: "#f5c6c6",
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
                                            ...prev, [selectedFile]: e.target.value
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

                        {/* lint output for selected file */}
                        {selectedFile && lintOutput[selectedFile] && (
                            <div style={{
                                marginTop: 8,
                                padding: "0.6rem 0.875rem",
                                borderRadius: "var(--radius)",
                                background: "var(--bg-warning)",
                                border: "0.5px solid var(--border-warning)"
                            }}>
                                <div style={{
                                    fontSize: 11, fontWeight: 500,
                                    color: "var(--text-warning)", marginBottom: 4
                                }}>
                                    <i className="ti ti-alert-triangle" aria-hidden style={{marginRight: 5}}/>
                                    Linter output — {selectedFile}
                                </div>
                                <pre style={{
                                    fontSize: 11, fontFamily: "var(--font-mono)",
                                    whiteSpace: "pre-wrap", margin: 0,
                                    color: "var(--text-secondary)",
                                    maxHeight: 120, overflowY: "auto"
                                }}>
                  {lintOutput[selectedFile]}
                </pre>
                            </div>
                        )}

                        {/* toggle edit mode */}
                        <div style={{marginTop: 8, display: "flex", gap: 8}}>
                            <button
                                onClick={() => setIsEditing(prev => !prev)}
                                style={{fontSize: 12}}
                            >
                                <i className={`ti ${isEditing ? "ti-eye" : "ti-edit"}`}
                                   aria-hidden style={{marginRight: 5}}/>
                                {isEditing ? "Back to diff view" : "Edit this file"}
                            </button>
                            {isEditing && (
                                <span style={{fontSize: 12, color: "var(--text-muted)", alignSelf: "center"}}>
                  editing {selectedFile}
                </span>
                            )}
                        </div>
                    </div>
                )}

                {/* ── REVIEW COMMENTS ── */}
                {reviewComments.length > 0 && (
                    <div style={{marginBottom: "1.25rem"}}>
                        <div style={{fontSize: 13, fontWeight: 500, marginBottom: 8, color: "var(--text-secondary)"}}>
                            Review comments
                        </div>
                        <div style={{display: "flex", flexDirection: "column", gap: 6}}>
                            {reviewComments.map((c, i) => (
                                <div key={i} style={{
                                    padding: "0.6rem 0.875rem",
                                    borderRadius: "var(--radius)",
                                    background: severityBg(c.severity),
                                    borderLeft: `3px solid ${severityColor(c.severity)}`
                                }}>
                                    <div style={{display: "flex", alignItems: "center", gap: 8, marginBottom: 3}}>
                    <span style={{
                        fontSize: 11, fontWeight: 500,
                        fontFamily: "var(--font-mono)",
                        color: severityColor(c.severity)
                    }}>
                      {c.severity?.toUpperCase()}
                    </span>
                                        <span style={{
                                            fontSize: 11, fontFamily: "var(--font-mono)",
                                            color: "var(--text-secondary)"
                                        }}>
                      {c.file}{c.line ? `:${c.line}` : ""}
                    </span>
                                    </div>
                                    <div style={{fontSize: 13, color: "var(--text-primary)"}}>
                                        {c.comment}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* ── TEST RESULTS ── */}
                {node === "hitl_tests" && (
                    <div style={{marginBottom: "1.25rem"}}>
                        <div style={{
                            padding: "0.875rem",
                            borderRadius: "var(--radius)",
                            background: `var(--bg-${testTone})`,
                            borderLeft: `3px solid var(--border-${testTone})`
                        }}>
                            <div style={{
                                fontSize: 13, fontWeight: 500, marginBottom: 4,
                                color: `var(--text-${testTone})`
                            }}>
                                {testHeadline}
                            </div>

                            {/* test command used */}
                            {testResults.test_command && (
                                <div style={{
                                    fontSize: 11, fontFamily: "var(--font-mono)",
                                    color: "var(--text-secondary)", marginBottom: 6
                                }}>
                                    <i className="ti ti-terminal" aria-hidden style={{marginRight: 5}}/>
                                    {testResults.test_command}
                                </div>
                            )}

                            {/* test files written */}
                            {testResults.test_files && Object.keys(testResults.test_files).length > 0 && (
                                <div style={{marginBottom: 8}}>
                                    <div style={{
                                        fontSize: 11, color: "var(--text-secondary)",
                                        marginBottom: 4
                                    }}>
                                        Test files written:
                                    </div>
                                    {Object.keys(testResults.test_files).map(f => (
                                        <div key={f} style={{
                                            fontSize: 11, fontFamily: "var(--font-mono)",
                                            color: "var(--text-secondary)"
                                        }}>
                                            <i className="ti ti-file-code" aria-hidden style={{marginRight: 5}}/>
                                            {f}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <pre style={{
                                fontSize: 11, fontFamily: "var(--font-mono)",
                                whiteSpace: "pre-wrap", margin: 0,
                                color: "var(--text-secondary)",
                                maxHeight: 200, overflowY: "auto"
                            }}>
                {testResults.output?.slice(0, 1500)}
              </pre>
                        </div>
                    </div>
                )}

                {/* ── PR LINK ── */}
                {node === "hitl_deploy" && payload.pr_url && (
                    <div style={{marginBottom: "1.25rem"}}>
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
                            <i className="ti ti-git-pull-request" aria-hidden style={{fontSize: 16}}/>
                            {payload.pr_url}
                            <i className="ti ti-external-link" aria-hidden style={{fontSize: 13}}/>
                        </a>
                    </div>
                )}

                {/* ── FEEDBACK ── */}
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

                {/* ── ACTIONS ── */}
                <div style={{display: "flex", gap: 8, flexWrap: "wrap"}}>
                    <button
                        onClick={() => resume("approved")}
                        disabled={submitting}
                        style={{
                            background: "var(--bg-success)",
                            color: "var(--text-success)",
                            border: "0.5px solid var(--border-success)"
                        }}
                    >
                        <i className="ti ti-check" aria-hidden style={{marginRight: 6}}/>
                        {node === "hitl_commit" ? "Approve — commit"
                            : node === "hitl_deploy" ? "Approve — deploy"
                                : node === "hitl_git_ops" ? "Approve — run it"
                                    : "Approve"}
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
                        <i className={`ti ${["hitl_commit", "hitl_deploy", "hitl_git_ops"].includes(node) ? "ti-x" : "ti-refresh"}`}
                           aria-hidden style={{marginRight: 6}}/>
                        {node === "hitl_plan" ? "Request changes"
                            : ["hitl_commit", "hitl_deploy", "hitl_git_ops"].includes(node) ? "Abort"
                                : "Reject — retry"}
                    </button>

                    {node === "hitl_code" && (
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
                            <i className="ti ti-device-floppy" aria-hidden style={{marginRight: 6}}/>
                            Save edits and continue
                        </button>
                    )}

                    {node === "hitl_tests" && !testResults.passed && (
                        <button
                            onClick={() => resume("override")}
                            disabled={submitting}
                        >
                            <i className="ti ti-alert-triangle" aria-hidden style={{marginRight: 6}}/>
                            Override — proceed anyway
                        </button>
                    )}
                </div>

                {submitting && (
                    <div style={{marginTop: 12, fontSize: 13, color: "var(--text-muted)"}}>
                        <i className="ti ti-loader" aria-hidden style={{marginRight: 6}}/>
                        Resuming pipeline...
                    </div>
                )}
            </div>
        </div>
    )
}