import { useEffect, useState } from 'react'
import { api, formatBytes, timeAgo, type BackupList } from '../api'

export default function Backups() {
  const [data, setData] = useState<BackupList | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const load = () => api.listBackups().then(setData).catch((e) => setError(e.message))
  useEffect(() => {
    load()
  }, [])

  async function backupNow() {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const b = await api.backupNow()
      setMessage(`Backup ${b.name} created.`)
      await load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function download(name: string) {
    setError('')
    try {
      await api.downloadBackup(name)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>Database backups</h1>
        <button className="primary" onClick={backupNow} disabled={busy}>
          {busy ? 'Backing up…' : 'Back up now'}
        </button>
      </header>
      {data && (
        <p className="muted">
          {data.daily_enabled
            ? `A backup is made automatically every day and kept for ${data.keep_days} days. `
            : 'Daily backups are off on this server (they run on the cloud server). '}
          Backups cover screens, loops, approvals and play history. Download one now and then to keep a copy off the
          server.
        </p>
      )}
      {message && <p className="notice">{message}</p>}
      {error && <p className="error">{error}</p>}
      {data && data.backups.length === 0 && <p className="empty">No backups yet.</p>}
      {data && data.backups.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Backup</th>
                <th>Made</th>
                <th>Size</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.backups.map((b) => (
                <tr key={b.name}>
                  <td>{b.name}</td>
                  <td>
                    {new Date(b.created_at).toLocaleString()} <span className="muted">({timeAgo(b.created_at)})</span>
                  </td>
                  <td>{formatBytes(b.size_bytes)}</td>
                  <td>
                    <button className="small" onClick={() => download(b.name)}>Download</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
