
import { useNavigate, useLocation } from "react-router-dom"

export default function Nav() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const username  = localStorage.getItem("username") || ""

  const logout = () => {
    localStorage.removeItem("token")
    localStorage.removeItem("username")
    navigate("/login")
  }

  const link = (path: string, icon: string, label: string) => {
    const active = location.pathname === path ||
      (path === "/history" && location.pathname.startsWith("/dashboard"))
    return (
      <button
        onClick={() => navigate(path)}
        style={{
          fontSize: 13, padding: "6px 12px",
          borderRadius: "var(--radius)",
          background: active ? "var(--bg-accent)" : "transparent",
          color: active ? "var(--text-accent)" : "var(--text-secondary)",
          border: active ? "0.5px solid var(--border-accent)" : "0.5px solid transparent"
        }}
      >
        <i className={`ti ${icon}`} aria-hidden style={{ marginRight: 6 }}/>
        {label}
      </button>
    )
  }

  return (
    <nav style={{
      display: "flex", alignItems: "center", gap: 6,
      padding: "0.75rem 1.5rem",
      borderBottom: "0.5px solid var(--border)",
      background: "var(--surface-2)"
    }}>
      <i className="ti ti-robot" aria-hidden
         style={{ fontSize: 20, color: "var(--text-accent)", marginRight: 8 }}/>
      {link("/intake",    "ti-plus",     "New task")}
      {link("/history",   "ti-history",  "History")}
      {link("/arch-docs", "ti-files",    "Arch docs")}

      <div style={{ marginLeft: "auto", display: "flex",
                    alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
          <i className="ti ti-user" aria-hidden style={{ marginRight: 5 }}/>
          {username}
        </span>
        <button onClick={logout} style={{ fontSize: 13 }}>
          <i className="ti ti-logout" aria-hidden style={{ marginRight: 5 }}/>
          Sign out
        </button>
      </div>
    </nav>
  )
}