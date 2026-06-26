import { useState } from "react"
import { useNavigate } from "react-router-dom"
import api from "../api/client"

export default function Login() {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError]       = useState("")
  const [loading, setLoading]   = useState(false)
  const navigate = useNavigate()

  const handleLogin = async () => {
    setLoading(true)
    setError("")
    try {
      const { data } = await api.post("/api/auth/login", { username, password })
      localStorage.setItem("token", data.token)
      localStorage.setItem("username", data.username)
      navigate("/")
    } catch {
      setError("Invalid username or password")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: "100vh", display: "flex",
      alignItems: "center", justifyContent: "center",
      background: "var(--surface-0)"
    }}>
      <div style={{
        width: 360, background: "var(--surface-2)",
        border: "0.5px solid var(--border)",
        borderRadius: 12, padding: "2rem"
      }}>
        <div style={{ marginBottom: "2rem", textAlign: "center" }}>
          <i className="ti ti-robot" aria-hidden
             style={{ fontSize: 32, color: "var(--text-accent)" }}/>
          <h1 style={{ fontSize: 20, fontWeight: 500, margin: "0.5rem 0 0.25rem" }}>
            Coding agent
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", margin: 0 }}>
            Sign in to continue
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label style={{ fontSize: 13, color: "var(--text-secondary)",
                            display: "block", marginBottom: 6 }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleLogin()}
              autoFocus
              style={{ width: "100%" }}
            />
          </div>
          <div>
            <label style={{ fontSize: 13, color: "var(--text-secondary)",
                            display: "block", marginBottom: 6 }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleLogin()}
              style={{ width: "100%" }}
            />
          </div>

          {error && (
            <div style={{
              fontSize: 13, color: "var(--text-danger)",
              background: "var(--bg-danger)",
              border: "0.5px solid var(--border-danger)",
              borderRadius: "var(--radius)", padding: "0.5rem 0.75rem"
            }}>
              <i className="ti ti-alert-circle" aria-hidden style={{ marginRight: 6 }}/>
              {error}
            </div>
          )}

          <button
            onClick={handleLogin}
            disabled={!username || !password || loading}
            style={{
              marginTop: 4,
              background: "var(--bg-accent)",
              color: "var(--text-accent)",
              border: "0.5px solid var(--border-accent)",
              width: "100%"
            }}
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </div>
      </div>
    </div>
  )
}