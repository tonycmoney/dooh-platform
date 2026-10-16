import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, dollars, monthLabel, type Host, type HostInput, type Screen } from '../api'
import { Modal } from '../components'

const PAYOUT_LABEL: Record<Host['payout_status'], [string, string]> = {
  not_started: ['Payouts not set up', 'status-muted'],
  pending: ['Payout setup in progress', 'status-pending'],
  ready: ['Payouts ready', 'status-approved'],
}

function HostForm({ host, onSaved, onClose }: { host?: Host; onSaved: (h: Host) => void; onClose: () => void }) {
  const [form, setForm] = useState<HostInput>({
    name: host?.name ?? '',
    business_name: host?.business_name ?? '',
    email: host?.email ?? '',
    phone: host?.phone ?? '',
    share_percent: host?.share_percent ?? 20,
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof HostInput) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: k === 'share_percent' ? Number(e.target.value) : e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      onSaved(host ? await api.updateHost(host.id, form) : await api.createHost(form))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={host ? 'Edit host' : 'Add host'} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <label>Business name<input value={form.business_name} onChange={set('business_name')} required autoFocus /></label>
        <label>Contact name<input value={form.name} onChange={set('name')} required /></label>
        <label>Email<input type="email" value={form.email ?? ''} onChange={set('email')} /></label>
        <label>Phone<input value={form.phone ?? ''} onChange={set('phone')} /></label>
        <label>
          Host share of ad revenue (%)
          <input type="number" min={0} max={100} value={form.share_percent} onChange={set('share_percent')} />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        </div>
      </form>
    </Modal>
  )
}

function ScreensPicker({ host, screens, hosts, onSaved, onClose }: {
  host: Host
  screens: Screen[]
  hosts: Host[]
  onSaved: (h: Host) => void
  onClose: () => void
}) {
  const [picked, setPicked] = useState(new Set(host.device_ids))
  const [error, setError] = useState('')
  const ownerOf = (id: string) => hosts.find((h) => h.id !== host.id && h.device_ids.includes(id))
  const toggle = (id: string) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setPicked(next)
  }
  async function save() {
    try {
      onSaved(await api.setHostScreens(host.id, [...picked]))
    } catch (err) {
      setError((err as Error).message)
    }
  }
  return (
    <Modal title={`Screens at ${host.business_name}`} onClose={onClose}>
      {screens.length === 0 && <p className="muted">No screens paired yet.</p>}
      <div className="form">
        {screens.map((s) => {
          const other = ownerOf(s.id)
          return (
            <label key={s.id} className="toggle">
              <input type="checkbox" checked={picked.has(s.id)} onChange={() => toggle(s.id)} />
              {s.name || 'Unnamed screen'} <span className="muted">{s.venue_name}</span>
              {other && <span className="muted">(now at {other.business_name}, will move)</span>}
            </label>
          )
        })}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button onClick={onClose}>Cancel</button>
        <button className="primary" onClick={save}>Save</button>
      </div>
    </Modal>
  )
}

/** Businesses hosting screens: what each one's screens earned, its private
 * link, and monthly payouts through Stripe. */
export default function Hosts() {
  const [hosts, setHosts] = useState<Host[] | null>(null)
  const [screens, setScreens] = useState<Screen[]>([])
  const [editing, setEditing] = useState<Host | 'new' | null>(null)
  const [picking, setPicking] = useState<Host | null>(null)
  const [copied, setCopied] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(() => {
    api.listHosts().then(setHosts).catch((e) => setError(e.message))
    api.listScreens().then(setScreens).catch(() => {})
  }, [])
  useEffect(load, [load])

  const replace = (h: Host) => {
    setHosts((list) => (list?.some((x) => x.id === h.id) ? list.map((x) => (x.id === h.id ? h : x)) : [...(list ?? []), h]))
    load()
  }

  async function copy(h: Host) {
    try {
      await navigator.clipboard.writeText(h.link)
      setCopied(h.id)
      setTimeout(() => setCopied(''), 2000)
    } catch {
      window.prompt('Copy this link:', h.link)
    }
  }

  async function pay(h: Host) {
    const m = h.last_month
    if (!window.confirm(`Send ${dollars(m.earnings)} to ${h.business_name} for ${monthLabel(m.month)}? This transfers real money from your Stripe balance.`)) return
    setBusy(h.id)
    setError('')
    try {
      await api.payHost(h.id, m.month)
      setNotice(`Sent ${dollars(m.earnings)} to ${h.business_name}.`)
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function resetLink(h: Host) {
    if (!window.confirm(`Make a new private link for ${h.business_name}? Their old link stops working.`)) return
    replace(await api.resetHostLink(h.id))
  }

  async function remove(h: Host) {
    if (!window.confirm(`Remove ${h.business_name}? Their screens stay paired, just without a host.`)) return
    try {
      await api.deleteHost(h.id)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const screenName = (id: string) => screens.find((s) => s.id === id)?.name || 'Screen'

  return (
    <div>
      <div className="page-head">
        <h1>Hosts</h1>
        <button className="primary" onClick={() => setEditing('new')}>+ Add host</button>
      </div>
      <p className="muted">
        Each host sees what their screens earned on a private page. Revenue is each advertiser's monthly payment,
        split by how long their ad played on each screen; the host earns their share of it.
      </p>
      {error && <p className="error">{error}</p>}
      {notice && <p className="notice">{notice}</p>}
      {hosts === null ? (
        <p className="muted">Loading…</p>
      ) : hosts.length === 0 ? (
        <div className="empty">No hosts yet. Add one, assign their screens and send them their link.</div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Host</th>
                <th>Screens</th>
                <th>This month</th>
                <th>Last month</th>
                <th>Payouts</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((h) => {
                const [label, tone] = PAYOUT_LABEL[h.payout_status]
                const last = h.last_month
                return (
                  <tr key={h.id}>
                    <td>
                      <b>{h.business_name}</b>
                      <div className="muted">{h.name}{h.email ? ` · ${h.email}` : ''}</div>
                      <div className="muted">{h.share_percent}% share</div>
                    </td>
                    <td>
                      {h.device_ids.length ? h.device_ids.map(screenName).join(', ') : <span className="muted">None</span>}
                      <div><button className="link small-text" onClick={() => setPicking(h)}>Change</button></div>
                    </td>
                    <td>
                      {dollars(h.this_month.earnings)}
                      <div className="muted">of {dollars(h.this_month.revenue)} revenue</div>
                    </td>
                    <td>
                      {dollars(last.earnings)}
                      <div className="muted">{monthLabel(last.month)}</div>
                      {last.payout ? (
                        <div className="status status-approved">✓ Paid {dollars(last.payout.amount)}</div>
                      ) : last.earnings > 0 && h.payout_status === 'ready' ? (
                        <button className="small primary" disabled={busy === h.id} onClick={() => pay(h)}>
                          {busy === h.id ? 'Sending…' : `Pay ${dollars(last.earnings)}`}
                        </button>
                      ) : null}
                    </td>
                    <td><span className={`status ${tone}`}>{label}</span></td>
                    <td>
                      <div className="card-actions">
                        <button className="small" onClick={() => copy(h)}>{copied === h.id ? 'Copied!' : 'Copy link'}</button>
                        <a className="small-text" href={h.link} target="_blank" rel="noreferrer">Open</a>
                        <button className="link small-text" onClick={() => setEditing(h)}>Edit</button>
                        <button className="link small-text" onClick={() => resetLink(h)}>New link</button>
                        <button className="link danger small-text" onClick={() => remove(h)}>Remove</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <HostForm
          host={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={(h) => {
            setEditing(null)
            replace(h)
          }}
        />
      )}
      {picking && hosts && (
        <ScreensPicker
          host={picking}
          screens={screens}
          hosts={hosts}
          onClose={() => setPicking(null)}
          onSaved={(h) => {
            setPicking(null)
            replace(h)
          }}
        />
      )}
    </div>
  )
}
