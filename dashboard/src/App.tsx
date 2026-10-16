import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api, getToken, setToken, setUnauthorizedHandler } from './api'
import Backups from './pages/Backups'
import HostPortal from './pages/HostPortal'
import Hosts from './pages/Hosts'
import LoopEditor from './pages/LoopEditor'
import Loops from './pages/Loops'
import MediaPage from './pages/Media'
import Orders from './pages/Orders'
import Reports from './pages/Reports'
import Screens from './pages/Screens'

function Login({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { token } = await api.login(password)
      setToken(token)
      onLogin()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1>DOOH Control</h1>
        <label>
          Admin password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}

export default function App() {
  // Hosts' private pages need no admin login.
  if (useLocation().pathname.startsWith('/host/')) {
    return (
      <Routes>
        <Route path="/host/:token" element={<HostPortal />} />
      </Routes>
    )
  }
  return <Admin />
}

function Admin() {
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getToken()))
  const [pending, setPending] = useState(0)
  const [ordersToReview, setOrdersToReview] = useState(0)

  // Stable, so pages can depend on it without reloading on every render.
  const refreshCounts = useCallback(() => {
    api.stats().then((s) => {
      setPending(s.pending_approvals)
      setOrdersToReview(s.orders_to_review)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null)
      setLoggedIn(false)
    })
  }, [])

  useEffect(() => {
    if (!loggedIn) return
    refreshCounts()
    const timer = setInterval(refreshCounts, 15000)
    return () => clearInterval(timer)
  }, [loggedIn, refreshCounts])

  if (!loggedIn) return <Login onLogin={() => setLoggedIn(true)} />

  return (
    <div className="shell">
      <nav className="sidebar">
        <div className="brand">DOOH Control</div>
        <NavLink to="/screens">Screens</NavLink>
        <NavLink to="/media">
          Media {pending > 0 && <span className="badge">{pending}</span>}
        </NavLink>
        <NavLink to="/orders">
          Orders {ordersToReview > 0 && <span className="badge">{ordersToReview}</span>}
        </NavLink>
        <NavLink to="/loops">Loops</NavLink>
        <NavLink to="/hosts">Hosts</NavLink>
        <NavLink to="/reports">Reports</NavLink>
        <NavLink to="/backups">Backups</NavLink>
        <button
          className="link logout"
          onClick={() => {
            setToken(null)
            setLoggedIn(false)
          }}
        >
          Sign out
        </button>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Navigate to="/screens" replace />} />
          <Route path="/screens" element={<Screens />} />
          <Route path="/media" element={<MediaPage onChanged={refreshCounts} />} />
          <Route path="/orders" element={<Orders onChanged={refreshCounts} />} />
          <Route path="/loops" element={<Loops />} />
          <Route path="/loops/:id" element={<LoopEditor />} />
          <Route path="/hosts" element={<Hosts />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/backups" element={<Backups />} />
          <Route path="*" element={<Navigate to="/screens" replace />} />
        </Routes>
      </main>
    </div>
  )
}
