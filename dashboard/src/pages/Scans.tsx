import { Fragment, useEffect, useMemo, useState } from 'react'
import { api, timeAgo, type QrDay, type QrLink } from '../api'

function Daily({ link }: { link: QrLink }) {
  const [days, setDays] = useState<QrDay[] | null>(null)
  useEffect(() => {
    api.qrDaily(link.id, 30).then(setDays).catch(() => setDays([]))
  }, [link.id])
  if (!days) return <p className="muted">Loading…</p>
  const max = Math.max(1, ...days.map((d) => d.scans))
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 64, margin: '0.4rem 0' }}>
        {days.map((d) => (
          <div
            key={d.day}
            title={`${d.day}: ${d.scans} scans, ${d.unique} people`}
            style={{ flex: 1, minWidth: 3, height: `${Math.max(2, (d.scans / max) * 100)}%`, background: d.scans ? 'var(--accent, #4f6bed)' : 'var(--border)', borderRadius: 2 }}
          />
        ))}
      </div>
      <p className="muted">
        Last 30 days, one bar per day. QR link: <a href={link.short_url} target="_blank" rel="noreferrer">{link.short_url}</a>
      </p>
    </div>
  )
}

function reportLine(l: QrLink) {
  return `${l.label}: ${l.scans_30d} QR scans in the last 30 days by ${l.unique_30d} ${l.unique_30d === 1 ? 'person' : 'different people'} (${l.scans_total} all time).`
}

export default function Scans() {
  const [links, setLinks] = useState<QrLink[] | null>(null)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)
  const [copied, setCopied] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const load = () => api.listQrLinks().then(setLinks).catch((e) => setError(e.message))
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (links ?? [])
      .filter((l) => !q || l.label.toLowerCase().includes(q) || (l.media_title ?? '').toLowerCase().includes(q))
      .sort((a, b) => b.scans_30d - a.scans_30d || b.scans_total - a.scans_total || a.label.localeCompare(b.label))
  }, [links, query])

  const totals = useMemo(() => {
    const all = links ?? []
    return {
      week: all.reduce((n, l) => n + l.scans_7d, 0),
      month: all.reduce((n, l) => n + l.scans_30d, 0),
      ever: all.reduce((n, l) => n + l.scans_total, 0),
    }
  }, [links])

  async function copy(l: QrLink) {
    try {
      await navigator.clipboard.writeText(reportLine(l))
      setCopied(l.id)
      setTimeout(() => setCopied(''), 2000)
    } catch {
      setError('Could not copy. Select the text instead: ' + reportLine(l))
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>QR scans</h1>
        <div className="head-actions">
          <input type="search" placeholder="Search business" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search business" />
        </div>
      </header>
      {error && <p className="error">{error}</p>}

      <div className="card" style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        <div><div className="muted">Last 7 days</div><strong style={{ fontSize: '1.6rem' }}>{totals.week}</strong></div>
        <div><div className="muted">Last 30 days</div><strong style={{ fontSize: '1.6rem' }}>{totals.month}</strong></div>
        <div><div className="muted">All time</div><strong style={{ fontSize: '1.6rem' }}>{totals.ever}</strong></div>
        <div><div className="muted">Tracked ads</div><strong style={{ fontSize: '1.6rem' }}>{links?.length ?? '…'}</strong></div>
      </div>
      <p className="muted" style={{ marginBottom: '1rem' }}>
        Every QR code on a tracked ad opens a short link here first, which counts the scan and then sends the phone to the map.
        "People" counts each phone once per day. Link previews and bots are not counted.
      </p>

      {links && links.length === 0 && <p className="muted">No tracked QR codes yet.</p>}
      {shown.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Business</th>
                <th>7 days</th>
                <th>30 days</th>
                <th>People (30 d)</th>
                <th>All time</th>
                <th>Last scan</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.map((l) => (
                <Fragment key={l.id}>
                  <tr>
                    <td>
                      <button className="link" onClick={() => setOpen(open === l.id ? null : l.id)}>{l.label}</button>
                      {!l.active && <span className="muted"> (paused)</span>}
                      {l.media_title && <div className="muted">{l.media_title}</div>}
                    </td>
                    <td>{l.scans_7d}</td>
                    <td><strong>{l.scans_30d}</strong></td>
                    <td>{l.unique_30d}</td>
                    <td>{l.scans_total}</td>
                    <td className="muted">{l.last_scan_at ? timeAgo(l.last_scan_at) : 'Never'}</td>
                    <td><button onClick={() => copy(l)}>{copied === l.id ? 'Copied' : 'Copy for advertiser'}</button></td>
                  </tr>
                  {open === l.id && (
                    <tr>
                      <td colSpan={7}><Daily link={l} /></td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
