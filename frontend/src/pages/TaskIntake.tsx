import {useState} from "react"
import {useNavigate} from "react-router-dom"
import axios from "axios"

export default function TaskIntake() {
    const [instructions, setInstructions] = useState("")
    const [files, setFiles] = useState<File[]>([])
    const [loading, setLoading] = useState(false)
    const navigate = useNavigate()

    const handleSubmit = async () => {
        setLoading(true)
        const form = new FormData()
        form.append("instructions", instructions)
        files.forEach(f => form.append("files", f))

        const {data} = await axios.post("http://localhost:8000/api/run", form)
        navigate(`/dashboard/${data.task_id}`)
    }

    return (
        <div style={{maxWidth: 720, margin: "0 auto", padding: "2rem 1rem"}}>
            <h1 style={{fontSize: 22, fontWeight: 500, marginBottom: "1.5rem"}}>
                New task
            </h1>

            <div style={{marginBottom: "1.5rem"}}>
                <label style={{
                    fontSize: 13, color: "var(--text-secondary)",
                    display: "block", marginBottom: 8
                }}>
                    Instructions
                </label>
                <textarea
                    value={instructions}
                    onChange={e => setInstructions(e.target.value)}
                    placeholder="Describe what you want the coding agent to build..."
                    rows={6}
                    style={{width: "100%", resize: "vertical"}}
                />
            </div>

            <div style={{marginBottom: "2rem"}}>
                <label style={{
                    fontSize: 13, color: "var(--text-secondary)",
                    display: "block", marginBottom: 8
                }}>
                    Documents (optional — PRDs, specs, examples)
                </label>
                <input
                    type="file"
                    multiple
                    accept=".md,.txt,.pdf,.ts,.py,.js"
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

            <button onClick={handleSubmit} disabled={!instructions || loading}>
                {loading ? "Starting..." : "Run pipeline ↗"}
            </button>
        </div>
    )
}