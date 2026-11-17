import { Fragment, useCallback, useEffect, useState, type FormEvent } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { dollars, hostApi, monthLabel, timeAgo, type HostAgreement, type HostPortal as Portal } from '../api'

function hours(seconds: number) {
  const h = seconds / 3600
  return h >= 10 ? `${Math.round(h)} h` : h >= 1 ? `${h.toFixed(1)} h` : `${Math.round(seconds / 60)} min`
}

const PHONE = '(475) 258 8963'

function AgreementCard({ agreement, token, onSigned }: {
  agreement: HostAgreement
  token: string
  onSigned: () => void
}) {
  const [name, setName] = useState('')
  const [agree, setAgree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(!agreement.signed)
  useEffect(() => { if (agreement.signed) setOpen(false) }, [agreement.signed])

  async function sign(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await hostApi.signAgreement(token, name.trim())
      onSigned()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={`hp-card hp-agreement${agreement.signed ? ' signed' : ''}`}>
      <div className="hp-label">Step 1 · Host agreement</div>
      {agreement.signed ? (
        <p>
          <b>✓ Signed</b> by {agreement.signed_name} on {new Date(agreement.signed_at!).toLocaleDateString()}. A copy
          was emailed to you.{' '}
          <button className="link" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'View agreement'}</button>
        </p>
      ) : (
        <p>Please read and sign your screen host agreement. Then you can set up payouts.</p>
      )}
      {open && (
        <div className="hp-agreement-text">
          <h2>{agreement.title}</h2>
          <p className="muted">{agreement.company_line}</p>
          <dl className="hp-dl">
            {agreement.details.map((d) => (
              <Fragment key={d.label}><dt>{d.label}</dt><dd>{d.value}</dd></Fragment>
            ))}
          </dl>
          {agreement.sections.map((s) => (
            <div key={s.heading}><h3>{s.heading}</h3><p>{s.body}</p></div>
          ))}
        </div>
      )}
      {!agreement.signed && (
        <form className="hp-sign" onSubmit={sign}>
          <label>
            Type your full name to sign
            <input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </label>
          <label className="hp-check">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            I have read and agree to this host agreement.
          </label>
          <button className="primary" disabled={busy || !agree || !name.trim()}>
            {busy ? 'Signing…' : 'I Agree, sign'}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      )}
    </section>
  )
}

function PayoutCard({ data, token }: { data: Portal; token: string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function setup() {
    setBusy(true)
    setError('')
    try {
      window.location.href = (await hostApi.payoutSetup(token)).url
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }
  const unsigned = data.agreement != null && !data.agreement.signed
  if (data.payout_status === 'ready') {
    return (
      <div className="hp-card hp-payout ready">
        <div className="hp-label">Payouts</div>
        <p><b>✓ You're all set.</b> Each month's earnings are sent to your bank account through Stripe after the month ends.</p>
      </div>
    )
  }
  return (
    <div className="hp-card hp-payout">
      <div className="hp-label">{data.agreement ? 'Step 2 · Payouts' : 'Payouts'}</div>
      <p>
        {unsigned ? 'Sign the host agreement above first, then connect your bank here.' : data.payout_status === 'pending'
          ? 'Your payout setup is almost done. Finish it on Stripe so we can send your earnings.'
          : 'Add your bank account through Stripe so we can send your earnings each month. It takes about 5 minutes.'}
      </p>
      {data.payouts_available ? (
        <button className="primary" onClick={setup} disabled={busy || unsigned}>
          {busy ? 'Opening Stripe…' : data.payout_status === 'pending' ? 'Finish payout setup' : 'Set up payouts'}
        </button>
      ) : (
        <p className="muted">Payout setup opens soon. We'll let you know.</p>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

/** A host's private page, reached by the secret link we send them. Shows
 * what their screens played and earned, and lets them set up payouts. */
export default function HostPortal() {
  const { token = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const month = params.get('month') ?? undefined
  const setupResult = params.get('setup')
  const [data, setData] = useState<Portal | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    hostApi.get(token, month).then(setData).catch((e) => setError(e.message))
  }, [token, month])
  useEffect(() => {
    load()
    const timer = setInterval(load, 60000)
    return () => clearInterval(timer)
  }, [load])
  useEffect(() => {
    document.title = data ? `${data.business_name} | Screen earnings` : 'Screen earnings'
  }, [data])

  if (error) {
    return (
      <div className="hp">
        <div className="hp-card hp-empty"><h1>Link not working</h1><p>{error}</p><p>Call Local Flyer Ads at {PHONE}.</p></div>
      </div>
    )
  }
  if (!data) return <div className="hp"><p className="muted">Loading your earnings…</p></div>

  const m = data.month
  const max = Math.max(1, ...data.history.map((h) => h.earnings))
  const totalPlays = m.screens.reduce((n, s) => n + s.plays, 0)
  const totalSeconds = m.screens.reduce((n, s) => n + s.seconds, 0)
  const isCurrent = data.history[0]?.month === m.month

  return (
    <div className="hp">
      <header className="hp-head">
        <div>
          <div className="hp-label">Local Flyer Ads · Host page</div>
          <h1>{data.business_name}</h1>
        </div>
        <select
          aria-label="Month"
          value={m.month}
          onChange={(e) => setParams(e.target.value === data.history[0]?.month ? {} : { month: e.target.value })}
        >
          {data.history.map((h) => <option key={h.month} value={h.month}>{monthLabel(h.month)}</option>)}
        </select>
      </header>

      {data.agreement && (
        <AgreementCard agreement={data.agreement} token={token} onSigned={load} />
      )}

      {setupResult === 'done' && data.payout_status !== 'ready' && (
        <p className="notice">Thanks! Stripe is reviewing your details. This page updates once payouts are ready.</p>
      )}

      <section className="hp-card hp-hero">
        <div className="hp-label">{isCurrent ? 'Earned so far this month' : `Earned in ${monthLabel(m.month)}`}</div>
        <div className="hp-big">{dollars(m.earnings)}</div>
        <div className="muted">
          {dollars(data.monthly_fee)} a month for each tablet you host{m.screens.length > 1 ? ` (${m.screens.length} tablets)` : ''}
        </div>
        <div className="hp-stats">
          <div><b>{totalPlays.toLocaleString()}</b><span>ad plays</span></div>
          <div><b>{hours(totalSeconds)}</b><span>of ads on screen</span></div>
          <div>
            <b>{m.payout ? `✓ ${dollars(m.payout.amount)}` : isCurrent ? 'Pending' : m.earnings > 0 ? 'Being sent' : '—'}</b>
            <span>{m.payout ? 'paid' : 'payout'}</span>
          </div>
        </div>
      </section>

      <h2>Your screens</h2>
      {m.screens.length === 0 ? (
        <div className="hp-card hp-empty">Your screen isn't connected to this page yet. We'll add it once it's installed.</div>
      ) : (
        <div className="hp-grid">
          {m.screens.map((s) => (
            <div className="hp-card" key={s.device_id}>
              <div className="hp-screen-head">
                <b>{s.name}</b>
                <span className={`pill ${s.online ? 'pill-on' : 'pill-off'}`}>{s.online ? 'Online' : 'Offline'}</span>
              </div>
              {!s.online && s.last_seen_at && <div className="muted">Last seen {timeAgo(s.last_seen_at)}. Check its power and WiFi.</div>}
              <dl className="hp-dl">
                <dt>Earned</dt><dd>{dollars(s.earnings)}</dd>
                <dt>Ad plays</dt><dd>{s.plays.toLocaleString()}</dd>
                <dt>Ads on screen</dt><dd>{hours(s.seconds)}</dd>
                <dt>Online time</dt><dd>{s.uptime_percent === null ? '—' : `${s.uptime_percent}%`}</dd>
              </dl>
            </div>
          ))}
        </div>
      )}

      <PayoutCard data={data} token={token} />

      <h2>Last 6 months</h2>
      <div className="hp-card">
        {data.history.map((h) => (
          <div className="hp-bar-row" key={h.month}>
            <span className="hp-bar-label">{monthLabel(h.month).replace(/ \d+$/, '')}</span>
            <span className="hp-bar"><span style={{ width: `${(100 * h.earnings) / max}%` }} /></span>
            <span className="hp-bar-value">{dollars(h.earnings)}{h.payout ? ' ✓' : ''}</span>
          </div>
        ))}
      </div>

      {data.payouts.length > 0 && (
        <>
          <h2>Payments sent</h2>
          <div className="hp-card">
            {data.payouts.map((p) => (
              <div className="hp-bar-row" key={p.month}>
                <span>{monthLabel(p.month)}</span>
                <span className="spacer" />
                <b>{dollars(p.amount)}</b>
                <span className="muted">sent {new Date(p.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <p className="muted hp-foot">
        How this works: you earn a flat {dollars(data.monthly_fee)} a month for each tablet you host, no matter how many
        ads play. Your first month counts from your start date. This month's amount grows day by day and is paid after
        the month ends. Times are {data.timezone.replace('_', ' ')}. Questions? Call {PHONE}.
      </p>
    </div>
  )
}
