import { useEffect, useState } from 'react'
import { api, type AlertRow, type DailyReport, type MonitoringStatus } from '../api'

const KIND = { offline: 'Offline', not_playing: 'Not playing' } as const

function time(iso: string, tz: string) {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: tz })
}

function dateTime(iso: string) {
  return new Date(iso).toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

function minutes(m: number) {
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`
}

export default function Reports() {
  const [report, setReport] = useState<DailyReport | null>(null)
  const [day, setDay] = useState('')
  const [status, setStatus] = useState<MonitoringStatus | null>(null)
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api.monitoring().then(setStatus).catch(() => {})
    api.listAlerts().then(setAlerts).catch(() => {})
  }, [])

  useEffect(() => {
    api.dailyReport(day || undefined)
      .then((r) => {
        setReport(r)
        if (!day) setDay(r.day)
      })
      .catch((e) => setError(e.message))
  }, [day])

  async function run(fn: () => Promise<{ sent_to: string[] }>, what: string) {
    setError('')
    setMessage('')
    try {
      const r = await fn()
      setMessage(`${what} sent to ${r.sent_to.join(', ')}.`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <header className="page-head">
        <h1>Reports & alerts</h1>
        <div className="head-actions">
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Report day" />
          <button onClick={() => run(() => api.emailReport(day), 'Report')} disabled={!status?.email_configured || !day}>
            Email this report
          </button>
        </div>
      </header>

      {status && (
        <div className={`card pin-card ${status.email_configured && status.monitoring ? '' : 'pin-missing'}`}>
          <div>
            <strong>Email alerts</strong>{' '}
            {status.email_configured && status.monitoring ? (
              <span className="ok-text">✓ on, to {status.alert_email_to.join(', ')}</span>
            ) : (
              <span className="warn-inline">
                ⚠ {status.monitoring ? 'email not set up (RESEND_API_KEY, ALERT_EMAIL_TO)' : 'monitoring is off (MONITORING=true)'}
              </span>
            )}
            <div className="muted small-text">
              An email when a screen is offline for {status.offline_minutes} min or stops playing for{' '}
              {status.not_playing_minutes} min, and again when it recovers. The daily report goes out at{' '}
              {status.report_hour}:00 ({status.timezone}) for the day before.
            </div>
          </div>
          <button className="small" disabled={!status.email_configured} onClick={() => run(api.testEmail, 'Test email')}>
            Send test email
          </button>
        </div>
      )}
      {message && <p className="notice">{message}</p>}
      {error && <p className="error">{error}</p>}

      {report && (
        <>
          <h2>Screens: {new Date(`${report.day}T12:00`).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}</h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Screen</th><th>Uptime</th><th>Online</th><th>Plays</th><th>Incidents</th></tr>
              </thead>
              <tbody>
                {report.screens.map((s) => (
                  <tr key={s.device_id}>
                    <td><strong>{s.name}</strong><div className="muted small-text">{s.venue_name}</div></td>
                    <td>
                      {s.uptime_percent === null ? '—' : (
                        <strong className={s.uptime_percent >= 95 ? 'ok-text' : 'error'}>{s.uptime_percent.toFixed(1)}%</strong>
                      )}
                    </td>
                    <td>{minutes(s.online_minutes)}</td>
                    <td>{s.plays}</td>
                    <td className="small-text">
                      {s.incidents.length === 0 ? <span className="muted">none</span> : s.incidents.map((i, n) => (
                        <div key={n}>
                          {KIND[i.kind]} {time(i.started_at, report.timezone)}–{i.resolved_at ? time(i.resolved_at, report.timezone) : 'still open'} ({minutes(i.minutes)})
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
                {report.screens.length === 0 && <tr><td colSpan={5} className="muted">No screens.</td></tr>}
              </tbody>
            </table>
          </div>

          <h2>Plays per ad ({report.total_plays} total)</h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Ad</th><th>Plays</th><th>Time on screen</th><th>Screens</th></tr>
              </thead>
              <tbody>
                {report.ads.map((a) => (
                  <tr key={a.title}><td>{a.title}</td><td>{a.plays}</td><td>{minutes(Math.round(a.seconds / 60))}</td><td>{a.screens ?? 1}</td></tr>
                ))}
                {report.ads.length === 0 && <tr><td colSpan={4} className="muted">No plays that day.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Recent alerts</h2>
      <div className="table-wrap">
        <table className="table compact">
          <thead>
            <tr><th>Screen</th><th>Problem</th><th>Started</th><th>Cleared</th><th>Emailed</th></tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <tr key={a.id}>
                <td>{a.screen}</td>
                <td>{KIND[a.kind]}<div className="muted small-text">{a.detail}</div></td>
                <td>{dateTime(a.started_at)}</td>
                <td>{a.resolved_at ? dateTime(a.resolved_at) : <span className="error">ongoing</span>}</td>
                <td>{a.emailed ? 'yes' : 'no'}</td>
              </tr>
            ))}
            {alerts.length === 0 && <tr><td colSpan={5} className="muted">No alerts yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
