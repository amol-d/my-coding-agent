import {useState} from "react"
import {useNavigate} from "react-router-dom"
import api from "../api/client"

export default function TaskIntake() {
    const [instructions, setInstructions] = useState("")
    const [files, setFiles] = useState<File[]>([])
    const [figmaLink, setFigmaLink] = useState("")
    const [createPr, setCreatePr] = useState(false)
    const [deploy, setDeploy] = useState(false)
    const [loading, setLoading] = useState(false)
    const navigate = useNavigate()

    const handleSubmit = async () => {
        setLoading(true)
        const form = new FormData()
        form.append("instructions", instructions)
        files.forEach(f => form.append("files", f))
        form.append("options", JSON.stringify({create_pr: createPr, deploy}))
        const links = figmaLink.trim() ? [figmaLink.trim()] : []
        form.append("figma_links", JSON.stringify(links))

        try {
            const {data} = await api.post("/api/run", form)
            navigate(`/dashboard/${data.task_id}`)
        } finally {
            setLoading(false)
        }
    }

    const labelStyle = {
        fontSize: 13, color: "var(--text-secondary)",
        display: "block", marginBottom: 8
    } as const

    return (
        <div style={{maxWidth: 720, margin: "0 auto", padding: "2rem 1rem"}}>
            <h1 style={{fontSize: 22, fontWeight: 500, marginBottom: "1.5rem"}}>
                New task
            </h1>

            <div style={{marginBottom: "1.5rem"}}>
                <label style={labelStyle}>Instructions</label>
                <textarea
                    value={instructions}
                    onChange={e => setInstructions(e.target.value)}
                    placeholder="Describe what you want the coding agent to build..."
                    rows={6}
                    style={{width: "100%", resize: "vertical"}}
                />
            </div>

            <div style={{marginBottom: "1.5rem"}}>
                <label style={labelStyle}>
                    Documents (optional — PRD/BRD PDF or .docx, architecture .md, or a
                    Figma design screenshot .png/.jpg)
                </label>
                <input
                    type="file"
                    multiple
                    accept=".md,.txt,.pdf,.docx,.png,.jpg,.jpeg,.py,.ts,.tsx,.js,.jsx,.json"
                    onChange={e => setFiles(Array.from(e.target.files || []))}
                />
                {files.length > 0 && (
                    <div style={{marginTop: 8, fontSize: 13, color: "var(--text-secondary)"}}>
                        {files.map(f => (
                            <div key={f.name}>
                                <i className="ti ti-file" aria-hidden style={{fontSize: 14, marginRight: 6}}/>
                                {f.name}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div style={{marginBottom: "1.5rem"}}>
                <label style={labelStyle}>Figma link (optional — paste for reference)</label>
                <input
                    type="url"
                    value={figmaLink}
                    onChange={e => setFigmaLink(e.target.value)}
                    placeholder="https://www.figma.com/file/..."
                    style={{width: "100%"}}
                />
                <div style={{fontSize: 12, color: "var(--text-muted)", marginTop: 4}}>
                    For the agent to “see” the design, also upload a screenshot above —
                    it is interpreted with a vision model.
                </div>
            </div>

            <div style={{
                marginBottom: "2rem", display: "flex", gap: 20, flexWrap: "wrap",
                padding: "0.875rem 1rem", borderRadius: "var(--radius)",
                border: "0.5px solid var(--border)", background: "var(--surface-1)"
            }}>
                <label style={{fontSize: 13, display: "flex", alignItems: "center", gap: 8, cursor: "pointer"}}>
                    <input type="checkbox" checked={createPr} onChange={e => setCreatePr(e.target.checked)}/>
                    Push branch &amp; open PR after commit
                </label>
                <label style={{fontSize: 13, display: "flex", alignItems: "center", gap: 8, cursor: "pointer"}}>
                    <input type="checkbox" checked={deploy} onChange={e => setDeploy(e.target.checked)}/>
                    Deploy after commit
                </label>
            </div>

            <button onClick={handleSubmit} disabled={!instructions || loading}>
                {loading ? "Starting..." : "Run pipeline ↗"}
            </button>
        </div>
    )
}
