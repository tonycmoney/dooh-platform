import { useCallback, useEffect, useRef, useState } from 'react'
import { UPLOAD_ACCEPT, api, timeAgo, uploadProblem, type Media, type Order } from '../api'
import { FormatPreview, MediaThumb } from '../components'

const REFRESH_MS = 15000

function orderState(o: Order): { label: string; tone: string } {
  if (o.file_status === 'queued') return { label: 'Preparing file…', tone: 'muted' }
  if (o.file_status === 'failed') return { label: 'File problem', tone: 'rejected' }
  if (!o.media) return { label: 'Needs your design', tone: 'pending' }
  if (o.media.status === 'pending') return { label: 'Waiting for approval', tone: 'pending' }
  if (o.media.status === 'approved') return { label: 'Approved', tone: 'approved' }
  return { label: 'Rejected', tone: 'rejected' }
}

/** Ad orders from the customer website. Their ads only play once approved
 * here (or on the Media page). */
export default function Orders({ onChanged }: { onChanged: () => void }) {
  const [orders, setOrders] = useState<Order[] | null>(null)
  const [previewing, setPreviewing] = useState<Media | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const attachFor = useRef<Order | null>(null)

  const load = useCallback(() => {
    api.listOrders().then(setOrders).catch((e) => setError(e.message))
    onChanged()
  }, [onChanged])

  useEffect(() => {
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  async function act(id: string, fn: () => Promise<unknown>) {
    setBusy(id)
    setError('')
    try {
      await fn()
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function chooseFile(o: Order) {
    attachFor.current = o
    fileInput.current?.click()
  }

  function onFile(file: File | undefined) {
    const o = attachFor.current
    if (!file || !o) return
    const problem = uploadProblem(file)
    if (problem) return setError(problem)
    act(o.id, () => api.attachOrderFile(o.id, file))
  }

  return (
    <div>
      <header className="page-head">
        <h1>Website orders</h1>
        <span className="muted">Screen ad orders from your website · ads play only after you approve them</span>
      </header>
      {error && <p className="error">{error}</p>}
      <input ref={fileInput} type="file" accept={UPLOAD_ACCEPT} hidden onChange={(e) => {
        onFile(e.target.files?.[0])
        e.target.value = ''
      }} />

      {orders && orders.length === 0 && (
        <p className="empty">No website orders yet. When a customer buys a screen ad spot, it shows up here.</p>
      )}

      <div className="orders">
        {orders?.map((o) => {
          const state = orderState(o)
          const m = o.media
          return (
            <div key={o.id} className="card order-card">
              <div className="order-ad">
                {m ? (
                  <button className="card-frame" onClick={() => setPreviewing(m)} title="Preview as screens show it">
                    <MediaThumb media={m} width={108} />
                  </button>
                ) : (
                  <div className="frame frame-empty" style={{ width: 108, height: 192 }}>
                    {o.file_status === 'queued' ? 'Preparing…' : 'No ad yet'}
                  </div>
                )}
              </div>
              <div className="order-info">
                <div className="order-title">
                  <strong>{o.business_name}</strong>
                  <span className={`status status-${state.tone}`}>{state.label}</span>
                </div>
                <div className="muted small-text">
                  {o.external_id} · {timeAgo(o.created_at)} ·{' '}
                  <a href={`https://dashboard.stripe.com/search?query=${encodeURIComponent(o.external_id)}`} target="_blank" rel="noreferrer">
                    find payment in Stripe
                  </a>
                </div>
                <dl className="order-fields">
                  <dt>Plan</dt><dd>{o.plan_name || o.plan}</dd>
                  {o.city && <><dt>City</dt><dd>{o.city}</dd></>}
                  <dt>Contact</dt>
                  <dd>
                    {o.contact_name && <>{o.contact_name} · </>}
                    <a href={`mailto:${o.email}`}>{o.email}</a>
                    {o.phone && <> · <a href={`tel:${o.phone}`}>{o.phone}</a></>}
                  </dd>
                  {o.ad_choice && <><dt>Ad</dt><dd>{o.ad_choice}{o.file_name ? ` (${o.file_name})` : ''}</dd></>}
                  {o.ad_text && <><dt>Ad should say</dt><dd className="pre">{o.ad_text}</dd></>}
                  {o.notes && <><dt>Notes</dt><dd className="pre">{o.notes}</dd></>}
                  {o.file_error && <><dt>File problem</dt><dd className="error">{o.file_error}</dd></>}
                </dl>
                <div className="card-actions">
                  {m && m.status !== 'approved' && (
                    <button className="primary small" disabled={busy === o.id} onClick={() => act(o.id, () => api.approve(m.id))}>
                      Approve ad
                    </button>
                  )}
                  {m && m.status === 'pending' && (
                    <button className="small" disabled={busy === o.id} onClick={() => act(o.id, () => api.reject(m.id))}>
                      Reject
                    </button>
                  )}
                  {m && <button className="small" onClick={() => setPreviewing(m)}>Preview</button>}
                  {o.can_retry && (
                    <button className="small" disabled={busy === o.id} onClick={() => act(o.id, () => api.retryOrderFile(o.id))}>
                      Retry download
                    </button>
                  )}
                  <button
                    className="small danger"
                    disabled={busy === o.id}
                    onClick={() => confirm(`Delete order ${o.external_id} from ${o.business_name}?${m && m.status !== 'approved' ? ' Its ad is deleted too.' : ''}`) && act(o.id, () => api.deleteOrder(o.id))}
                  >
                    Delete
                  </button>
                  {o.file_status !== 'queued' && (
                    <button className="small" disabled={busy === o.id} onClick={() => chooseFile(o)}>
                      {busy === o.id ? 'Uploading…' : m ? 'Replace ad file' : 'Upload the ad'}
                    </button>
                  )}
                </div>
                {m?.status === 'approved' && (
                  <p className="muted small-text">Approved. Add it to a loop on the Loops page to put it on screens.</p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {previewing && (
        <FormatPreview
          media={orders?.flatMap((o) => (o.media ? [o.media] : [])).find((m) => m.id === previewing.id) ?? previewing}
          onClose={() => setPreviewing(null)}
          onChanged={(m) => {
            setPreviewing(m)
            load()
          }}
        />
      )}
    </div>
  )
}
