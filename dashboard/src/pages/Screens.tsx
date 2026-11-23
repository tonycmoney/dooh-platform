import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import { api, timeAgo, type ConnectionMode, type LoopSummary, type PlayLog, type Screen } from '../api'
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
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          referrerPolicy="strict-origin-when-cross-origin"
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

const MODE_HELP: Record<ConnectionMode, string> = {
  wifi: 'On the host’s WiFi. You get an email when it drops, and the tablet logs every outage.',
  offline: 'No WiFi at this venue. It plays the ads saved on it; stop by with your iPhone hotspot on to load new ads and upload its plays. No offline alerts.',
}

function ConnectionField({ value, onChange }: { value: ConnectionMode; onChange: (m: ConnectionMode) => void }) {
  return (
    <label>
      How it gets online
      <select value={value} onChange={(e) => onChange(e.target.value as ConnectionMode)}>
        <option value="wifi">Host WiFi</option>
        <option value="offline">Offline, I sync it</option>
      </select>
      <span className="muted small-text">{MODE_HELP[value]}</span>
    </label>
  )
}

function duration(minutes: number) {
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h} hr ${m} min` : `${h} hr`
}

function outageText(o: { started_at: string; minutes: number }) {
  const at = new Date(o.started_at)
  return `${at.toLocaleDateString(undefined, { weekday: 'short' })} ${at.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}, down ${duration(o.minutes)}`
}

/** Status pill: offline screens are "Offline" by design, so they read as their sync state. */
function StatusPill({ s }: { s: Screen }) {
  if (s.connection_mode === 'offline') {
    if (s.online) return <span className="pill on">Syncing</span>
    return <span className={`pill ${s.needs_visit ? 'off' : 'idle'}`}>{s.needs_visit ? 'Needs visit' : 'Offline · OK'}</span>
  }
  return <span className={`pill ${s.online ? 'on' : 'off'}`}>{s.online ? 'Online' : 'Offline'}</span>
}

/** Offline screens to stop by, in one list, so a route is easy to plan. */
function VisitList({ screens, onOpen }: { screens: Screen[]; onOpen: (s: Screen) => void }) {
  const due = screens.filter((s) => s.needs_visit)
  if (due.length === 0) return null
  return (
    <div className="card visit-card">
      <strong>Screens to visit ({due.length})</strong>
      <div className="muted small-text">Turn on your iPhone hotspot when you get there. The tablet joins it, loads new ads and uploads its plays in a few minutes.</div>
      <ul className="visit-list">
        {due.map((s) => (
          <li key={s.id} onClick={() => onOpen(s)} className="clickable">
            <strong>{s.name}</strong> · {s.venue_name}
            {s.venue_address && (
              <>
                {' · '}
                <a href={`https://maps.apple.com/?q=${encodeURIComponent(s.venue_address)}`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                  {s.venue_address}
                </a>
              </>
            )}
            <div className="muted small-text">{s.visit_reasons.join(' · ')} · last synced {timeAgo(s.last_seen_at)}</div>
          </li>
        ))}
      </ul>
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

/** The PIN technicians enter on a tablet after the secret tap pattern
 * (corners clockwise from top-left) to open its maintenance panel. */
function MaintenancePinCard() {
  const [isSet, setIsSet] = useState<boolean | null>(null)
  const [editing, setEditing] = useState(false)
  const [pin, setPin] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api.getSettings().then((s) => setIsSet(s.maintenance_pin_set)).catch(() => {})
  }, [])

  async function save(e: FormEvent) {
    e.preventDefault()
    setError('')
    try {
      const s = await api.setMaintenancePin(pin)
      setIsSet(s.maintenance_pin_set)
      setEditing(false)
      setPin('')
      setMessage('PIN saved. Tablets pick it up within a minute.')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  if (isSet === null) return null
  return (
    <div className={`card pin-card ${isSet ? '' : 'pin-missing'}`}>
      <div>
        <strong>Tablet maintenance PIN</strong>{' '}
        {isSet ? <span className="ok-text">✓ set</span> : <span className="warn-inline">⚠ not set: anyone who finds the tap pattern can open a tablet's settings</span>}
        <div className="muted small-text">
          To exit kiosk mode on a tablet: tap its four corners clockwise, starting top-left, then enter this PIN.
        </div>
        {message && <div className="ok-text small-text">{message}</div>}
      </div>
      {editing ? (
        <form className="pin-form" onSubmit={save}>
          <input
            type="password"
            inputMode="numeric"
            autoComplete="new-password"
            placeholder="4–8 digits"
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 8))}
            autoFocus
          />
          <button className="primary small" disabled={pin.length < 4}>Save PIN</button>
          <button type="button" className="small" onClick={() => { setEditing(false); setPin('') }}>Cancel</button>
          {error && <span className="error small-text">{error}</span>}
        </form>
      ) : (
        <button className="small" onClick={() => { setEditing(true); setMessage('') }}>{isSet ? 'Change PIN' : 'Set PIN'}</button>
      )}
    </div>
  )
}

function PairDialog({ loops, screens, onClose, onPaired }: {
  loops: LoopSummary[]
  screens: Screen[]
  onClose: () => void
  onPaired: () => void
}) {
  const [form, setForm] = useState({ pairing_code: '', name: '', venue_name: '', venue_address: '', loop_id: '', replaces: '' })
  const [mode, setMode] = useState<ConnectionMode>('wifi')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }))

  /** Swapping tablets: start from the replaced screen's details. */
  function chooseReplaced(id: string) {
    const old = screens.find((s) => s.id === id)
    setForm((f) => ({
      ...f,
      replaces: id,
      ...(old ? { name: old.name ?? '', venue_name: old.venue_name ?? '', venue_address: old.venue_address ?? '' } : {}),
    }))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    const old = screens.find((s) => s.id === form.replaces)
    if (old && !confirm(`Replace “${old.name}”? The new tablet takes over its loop and play history, and the old tablet is unpaired.`)) return
    setBusy(true)
    setError('')
    try {
      const { replaces, ...rest } = form
      await api.pairScreen({
        ...rest,
        pairing_code: form.pairing_code.trim().toUpperCase(),
        loop_id: form.loop_id || null,
        replaces_device_id: replaces || null,
        connection_mode: mode,
      })
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
        {screens.length > 0 && (
          <label>
            Replaces an existing screen? (swapping a tablet)
            <select value={form.replaces} onChange={(e) => chooseReplaced(e.target.value)}>
              <option value="">No, this is a new screen</option>
              {screens.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.venue_name}</option>)}
            </select>
          </label>
        )}
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
        {!form.replaces && <ConnectionField value={mode} onChange={setMode} />}
        <label>
          {form.replaces ? 'Loop to play (empty = keep the replaced screen’s loop)' : 'Loop to play (optional)'}
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
  const [mode, setMode] = useState<ConnectionMode>(screen.connection_mode)
  const [plays, setPlays] = useState<PlayLog[]>([])
  const [error, setError] = useState('')
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }))

  useEffect(() => {
    api.screenPlays(screen.id).then(setPlays).catch(() => {})
  }, [screen.id])

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      // Only send a loop change when the user actually picked a different
      // loop, so editing the name or venue can never unassign content.
      const loopChanged = form.loop_id !== (screen.loop_id ?? '')
      await api.updateScreen(screen.id, {
        name: form.name,
        venue_name: form.venue_name,
        venue_address: form.venue_address,
        connection_mode: mode,
        ...(loopChanged ? (form.loop_id ? { loop_id: form.loop_id } : { clear_loop: true }) : {}),
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
        <ConnectionField value={mode} onChange={setMode} />
        {screen.wifi_unreliable && mode === 'wifi' && (
          <p className="warn-inline small-text">
            This WiFi dropped {screen.outages_7d} times ({duration(screen.outage_minutes_7d)} down) in the last 7 days. Consider switching to Offline, I sync it.
          </p>
        )}
        {screen.needs_visit && <p className="warn-inline small-text">Needs a visit: {screen.visit_reasons.join(' · ')}</p>}
        <label>
          Loop
          <select value={form.loop_id} onChange={(e) => set('loop_id', e.target.value)}>
            {form.loop_id && !loops.some((l) => l.id === form.loop_id) && (
              <option value={form.loop_id}>{screen.loop_name ?? 'Current loop'}</option>
            )}
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
      {screen.connection_mode === 'wifi' && screen.recent_outages.length > 0 && (
        <>
          <h3>Connection drops (last 7 days)</h3>
          <p className="muted small-text">Logged by the tablet itself, so you can show the venue exactly when its WiFi was down.</p>
          <ul className="outage-list">
            {screen.recent_outages.map((o) => <li key={o.started_at}>{outageText(o)}</li>)}
          </ul>
          {screen.outages_7d > screen.recent_outages.length && (
            <p className="muted small-text">and {screen.outages_7d - screen.recent_outages.length} more ({duration(screen.outage_minutes_7d)} down in total)</p>
          )}
        </>
      )}
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

  const wifiScreens = screens.filter((s) => s.connection_mode === 'wifi')
  const online = wifiScreens.filter((s) => s.online).length
  const offlineCount = screens.length - wifiScreens.length

  return (
    <div>
      <header className="page-head">
        <h1>Screens</h1>
        <div className="head-actions">
          <span className="muted">{online} of {wifiScreens.length} WiFi screens online{offlineCount > 0 && ` · ${offlineCount} offline by design`} · refreshes every 15s</span>
          <button className="primary" onClick={() => setPairing(true)}>+ Pair new screen</button>
        </div>
      </header>
      {error && <p className="error">{error}</p>}

      <MaintenancePinCard />

      <VisitList screens={screens} onOpen={setEditing} />

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
                  <td><StatusPill s={s} /></td>
                  <td>
                    <strong>{s.name}</strong>
                    <div className="muted small-text">{s.connection_mode === 'wifi' ? 'Host WiFi' : 'Offline, I sync it'}</div>
                    {s.wifi_unreliable && s.connection_mode === 'wifi' && (
                      <div className="warn-inline small-text">WiFi dropped {s.outages_7d}× this week</div>
                    )}
                  </td>
                  <td>{s.venue_name}<div className="muted">{s.venue_address}</div></td>
                  <td className="muted">
                    {s.latitude != null ? (
                      <>
                        {s.latitude.toFixed(5)}, {s.longitude!.toFixed(5)}
                        {s.location_accuracy_m != null && <div>±{Math.round(s.location_accuracy_m)} m</div>}
                      </>
                    ) : 'No GPS yet'}
                  </td>
                  <td title={s.last_seen_at ? new Date(s.last_seen_at).toLocaleString() : ''}>
                    {timeAgo(s.last_seen_at)}
                    {s.connection_mode === 'offline' && !s.online && <div className="muted small-text">last sync</div>}
                  </td>
                  <td>{s.online ? (s.now_playing_title ?? <span className="muted">Nothing</span>) : <span className="muted">—</span>}</td>
                  <td>
                    {s.loop_name ?? <span className="muted">None</span>}
                    {s.loop_name && !s.in_sync && (
                      <div className="muted">{s.connection_mode === 'offline' && !s.online ? 'new ads on next visit' : 'updating…'}</div>
                    )}
                  </td>
                  <td><Battery level={s.battery_level} charging={s.is_charging} /></td>
                  <td className="muted">{s.app_version ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pairing && <PairDialog loops={loops} screens={screens} onClose={() => setPairing(false)} onPaired={() => { setPairing(false); load() }} />}
      {editing && (
        <EditDialog screen={editing} loops={loops} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />
      )}
    </div>
  )
}
