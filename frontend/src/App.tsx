import './App.css'

// import {BrowserRouter, Navigate, Route, Routes} from "react-router-dom"
// import TaskIntake from "./pages/TaskIntake"
// import Dashboard from "./pages/Dashboard"

// export default function App() {
//     return (
//         <BrowserRouter>
//             <Routes>
//                 <Route path="/" element={<Navigate to="/intake"/>}/>
//                 <Route path="/intake" element={<TaskIntake/>}/>
//                 <Route path="/dashboard/:taskId" element={<Dashboard/>}/>
//             </Routes>
//         </BrowserRouter>
//     )
// }

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import Login      from "./pages/Login"
import TaskIntake from "./pages/TaskIntake"
import Dashboard  from "./pages/Dashboard"
import RunHistory from "./pages/RunHistory"
import ArchDocs   from "./pages/ArchDocs"
import Nav        from "./components/Nav"

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem("token")
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", background: "var(--surface-0)" }}>
      <Nav />
      {children}
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Navigate to="/history" replace />} />
        <Route path="/intake" element={
          <RequireAuth><Layout><TaskIntake /></Layout></RequireAuth>
        }/>
        <Route path="/history" element={
          <RequireAuth><Layout><RunHistory /></Layout></RequireAuth>
        }/>
        <Route path="/dashboard/:taskId" element={
          <RequireAuth><Layout><Dashboard /></Layout></RequireAuth>
        }/>
        <Route path="/arch-docs" element={
          <RequireAuth><Layout><ArchDocs /></Layout></RequireAuth>
        }/>
      </Routes>
    </BrowserRouter>
  )
}