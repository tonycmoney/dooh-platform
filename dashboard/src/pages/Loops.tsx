import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, formatDuration, timeAgo, type LoopSummary } from '../api'

export default function Loops() {
  const [loops, setLoops] = useState<LoopSummary[]>([])
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    api.listLoops().then(setLoops).catch((e) => setError(e.message))
  }, [])

  async function create(e: FormEvent) {
    e.preventDefault()
    try {
      const loop = await api.createLoop(name.trim())
      navigate(`/loops/${loop.id}`)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>Loops</h1>
        <form className="head-actions" onSubmit={create}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New loop name" />
          <button className="primary" disabled={!name.trim()}>Create loop</button>
        </form>
      </header>
      {error && <p className="error">{error}</p>}
      {loops.length === 0 ? (
        <p className="empty">No loops yet. Create one, add media to it, then assign it to screens.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Loop</th>
              <th>Items</th>
              <th>Length</th>
              <th>Screens</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {loops.map((l) => (
              <tr key={l.id}>
                <td><Link to={`/loops/${l.id}`}>{l.name}</Link></td>
                <td>{l.item_count}</td>
                <td>{formatDuration(l.total_seconds)}</td>
                <td>{l.device_count}</td>
                <td className="muted">{timeAgo(l.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
