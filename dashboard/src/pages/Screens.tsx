import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import { api, timeAgo, type LoopSummary, type PlayLog, type Screen } from '../api'
import { Modal } from '../components'

const REFRESH_MS = 15000

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap()
  const key = points.map((p) => p.join(',')).join(';')
  useEffect(() => {
    if (points.length === 1) map.setView(points[0], 15)
    else if (points.length > 1) map.fitBounds(points, { padding: [40, 40] })
    // Only refit when the set of locations changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, map])
  return null
}

function ScreensMap({ screens }: { screens: Screen[] }) {
  const located = screens.filter((s) => s.latitude != null && s.longitude != null)
  const points = located.map((s) => [s.latitude!, s.longitude!] as [number, number])
  return (
    <div className="map card">
      <MapContainer center={[39.5, -98.35]} zoom={4} scrollWheelZoom={false} style={{ height: '100%' }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds points={points} />
        {located.map((s) => (
          <CircleMarker
            key={s.id}
            center={[s.latitude!, s.longitude!]}
            radius={10}
            pathOptions={{ color: '#fff', weight: 2, fillColor: s.online ? '#16a34a' : '#dc2626', fillOpacity: 1 }}
          >
            <Popup>
              <strong>{s.name}</strong>
              <br />
              {s.venue_name}
              <br />
              {s.venue_address}
              <br />
              {s.online ? 'Online' : 'Offline'} · {timeAgo(s.last_seen_at)}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
      {located.length === 0 && <div className="map-empty">No GPS locations reported yet</div>}
    </div>
  )
}

function Battery({ level, charging }: { level: number | null; charging: boolean | null }) {
  if (level == null) return <span className="muted">—</span>
  const cls = level <= 15 ? 'low' : level <= 40 ? 'mid' : 'ok'
  return (
    <span className={`battery ${cls}`}>
      {level}%{charging ? ' ⚡' : ''}
    </span>
  )
}

function PairDialog({ loops, onClose, onPaired }: { loops: LoopSummary[]; onClose: () => void; onPaired: () => void }) {
  const [form, setForm] = useState({ pairing_code: '', name: '', venue_name: '', venue_address: '', loop_id: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.pairScreen({ ...form, pairing_code: form.pairing_code.trim().toUpperCase(), loop_id: form.loop_id || null })
      onPaired()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Pair a new screen" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          Pairing code shown on the tablet
          <input
            className="code-input"
            value={form.pairing_code}
            onChange={(e) => set('pairing_code', e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6))}
            placeholder="ABC123"
            autoFocus
            required
          />
        </label>
        <label>
          Screen name
          <input value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Front counter" required />
        </label>
        <label>
          Venue name
          <input value={form.venue_name} onChange={(e) => set('venue_name', e.target.value)} placeholder="e.g. Joe's Barbershop" required />
        </label>
        <label>
          Venue address
          <input value={form.venue_address} onChange={(e) => set('venue_address', e.target.value)} placeholder="123 Main St, Springfield" />
        </label>
        <label>
          Loop to play (optional)
          <select value={form.loop_id} onChange={(e) => set('loop_id', e.target.value)}>
            <option value="">None yet</option>
            {loops.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || form.pairing_code.length !== 6}>{busy ? 'Pairing…' : 'Pair screen'}</button>
        </div>
      </form>
    </Modal>
  )
}

function EditDialog({ screen, loops, onClose, onSaved }: {
  screen: Screen
  loops: LoopSummary[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState({
    name: screen.name ?? '',
    venue_name: screen.venue_name ?? '',
    venue_address: screen.venue_address ?? '',
    loop_id: screen.loop_id ?? '',
  })
  const [plays, setPlays] = useState<PlayLog[]>([])
  const [error, setError] = useState('')
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }))

  useEffect(() => {
    api.screenPlays(screen.id).then(setPlays).catch(() => {})
  }, [screen.id])

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      await api.updateScreen(screen.id, {
        name: form.name,
        venue_name: form.venue_name,
        venue_address: form.venue_address,
        ...(form.loop_id ? { loop_id: form.loop_id } : { clear_loop: true }),
      })
      onSaved()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function unpair() {
    if (!confirm(`Unpair "${screen.name}"? The tablet will stop playing and show a new pairing code.`)) return
    await api.unpairScreen(screen.id)
    onSaved()
  }

  return (
    <Modal title={screen.name ?? 'Screen'} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>Screen name<input value={form.name} onChange={(e) => set('name', e.target.value)} required /></label>
        <label>Venue name<input value={form.venue_name} onChange={(e) => set('venue_name', e.target.value)} required /></label>
        <label>Venue address<input value={form.venue_address} onChange={(e) => set('venue_address', e.target.value)} /></label>
        <label>
          Loop
          <select value={form.loop_id} onChange={(e) => set('loop_id', e.target.value)}>
            <option value="">None (blank screen)</option>
            {loops.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        <p className="muted small-text">Device ID: {screen.device_uid}</p>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" className="danger" onClick={unpair}>Unpair</button>
          <span className="spacer" />
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary">Save</button>
        </div>
      </form>
      <h3>Recent plays (proof of play)</h3>
      {plays.length === 0 ? (
        <p className="muted">No plays logged yet.</p>
      ) : (
        <table className="table compact">
          <tbody>
            {plays.map((p) => (
              <tr key={p.id}>
                <td>{new Date(p.started_at).toLocaleTimeString()}</td>
                <td>{p.media_title}</td>
                <td className="muted">{(p.duration_ms / 1000).toFixed(1)}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  )
}

export default function Screens() {
  const [screens, setScreens] = useState<Screen[]>([])
  const [loops, setLoops] = useState<LoopSummary[]>([])
  const [pairing, setPairing] = useState(false)
  const [editing, setEditing] = useState<Screen | null>(null)
  const [error, setError] = useState('')
  const [, setTick] = useState(0)

  const load = useCallback(() => {
    api.listScreens().then((s) => {
      setScreens(s)
      setError('')
    }).catch((e) => setError(e.message))
    api.listLoops().then(setLoops).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const refresh = setInterval(load, REFRESH_MS)
    const clock = setInterval(() => setTick((t) => t + 1), 5000) // keep "x ago" fresh
    return () => {
      clearInterval(refresh)
      clearInterval(clock)
    }
  }, [load])

  const online = screens.filter((s) => s.online).length

  return (
    <div>
      <header className="page-head">
        <h1>Screens</h1>
        <div className="head-actions">
          <span className="muted">{online} of {screens.length} online · refreshes every 15s</span>
          <button className="primary" onClick={() => setPairing(true)}>+ Pair new screen</button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}

      <ScreensMap screens={screens} />

      {screens.length === 0 ? (
        <p className="empty">No screens yet. Open the player app on a tablet, then click “Pair new screen” and enter the code it shows.</p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Screen</th>
                <th>Venue</th>
                <th>Location</th>
                <th>Last seen</th>
                <th>Playing now</th>
                <th>Loop</th>
                <th>Battery</th>
                <th>App</th>
              </tr>
            </thead>
            <tbody>
              {screens.map((s) => (
                <tr key={s.id} onClick={() => setEditing(s)} className="clickable">
                  <td><span className={`pill ${s.online ? 'on' : 'off'}`}>{s.online ? 'Online' : 'Offline'}</span></td>
                  <td><strong>{s.name}</strong></td>
                  <td>{s.venue_name}<div className="muted">{s.venue_address}</div></td>
                  <td className="muted">
                    {s.latitude != null ? (
                      <>
                        {s.latitude.toFixed(5)}, {s.longitude!.toFixed(5)}
                        {s.location_accuracy_m != null && <div>±{Math.round(s.location_accuracy_m)} m</div>}
                      </>
                    ) : 'No GPS yet'}
                  </td>
                  <td title={s.last_seen_at ? new Date(s.last_seen_at).toLocaleString() : ''}>{timeAgo(s.last_seen_at)}</td>
                  <td>{s.online ? (s.now_playing_title ?? <span className="muted">Nothing</span>) : <span className="muted">—</span>}</td>
                  <td>
                    {s.loop_name ?? <span className="muted">None</span>}
                    {s.loop_name && !s.in_sync && <div className="muted">updating…</div>}
                  </td>
                  <td><Battery level={s.battery_level} charging={s.is_charging} /></td>
                  <td className="muted">{s.app_version ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pairing && <PairDialog loops={loops} onClose={() => setPairing(false)} onPaired={() => { setPairing(false); load() }} />}
      {editing && (
        <EditDialog screen={editing} loops={loops} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />
      )}
    </div>
  )
}
