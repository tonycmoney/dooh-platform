import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { UPLOAD_ACCEPT, api, formatBytes, uploadProblem, type ApprovalStatus, type Media, type TextSlideInput } from '../api'
import { KindTag, MediaThumb, Modal, TextSlidePreview } from '../components'

interface UploadJob {
  id: number
  name: string
  progress: number
  error?: string
  note?: string
}

/** Files dropped from apps like Photos sometimes arrive only as items. */
function droppedFiles(data: DataTransfer): File[] {
  if (data.files.length) return Array.from(data.files)
  return Array.from(data.items)
    .filter((item) => item.kind === 'file')
    .map((item) => item.getAsFile())
    .filter((f): f is File => f !== null)
}
const FILTERS: (ApprovalStatus | 'all')[] = ['all', 'pending', 'approved', 'rejected']

export function TextSlideEditor({ initial, onSaved, onClose }: {
  initial?: Media
  onSaved: (m: Media) => void
  onClose: () => void
}) {
  const [form, setForm] = useState<TextSlideInput>({
    title: initial?.title ?? '',
    text: initial?.text ?? '',
    font_size: initial?.font_size ?? 96,
    text_color: initial?.text_color ?? '#FFFFFF',
    background_color: initial?.background_color ?? '#000000',
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof TextSlideInput>(key: K, value: TextSlideInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = { ...form, title: form.title.trim() || form.text.slice(0, 40) }
      onSaved(initial ? await api.updateTextSlide(initial.id, body) : await api.createTextSlide(body))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={initial ? 'Edit text slide' : 'New text slide'} onClose={onClose}>
      <form className="slide-editor" onSubmit={submit}>
        <TextSlidePreview
          text={form.text}
          fontSize={form.font_size}
          textColor={form.text_color}
          backgroundColor={form.background_color}
          height={270}
        />
        <label>
          Title (for your list)
          <input value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Happy hour promo" />
        </label>
        <label>
          Text on screen
          <textarea rows={3} value={form.text} onChange={(e) => set('text', e.target.value)} required />
        </label>
        <div className="row">
          <label>
            Font size: {form.font_size}
            <input type="range" min={24} max={300} value={form.font_size} onChange={(e) => set('font_size', Number(e.target.value))} />
          </label>
          <label>
            Text color
            <input type="color" value={form.text_color} onChange={(e) => set('text_color', e.target.value.toUpperCase())} />
          </label>
          <label>
            Background
            <input type="color" value={form.background_color} onChange={(e) => set('background_color', e.target.value.toUpperCase())} />
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !form.text.trim()}>
            {busy ? 'Saving…' : 'Save slide'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function MediaPage({ onChanged }: { onChanged: () => void }) {
  const [media, setMedia] = useState<Media[]>([])
  const [filter, setFilter] = useState<ApprovalStatus | 'all'>('all')
  const [autoApprove, setAutoApprove] = useState(true)
  const [uploads, setUploads] = useState<UploadJob[]>([])
  const [editing, setEditing] = useState<Media | 'new' | null>(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const jobId = useRef(0)

  const load = useCallback(() => {
    api.listMedia().then(setMedia).catch((e) => setError(e.message))
    onChanged()
  }, [onChanged])

  useEffect(() => {
    load()
    api.getSettings().then((s) => setAutoApprove(s.auto_approve)).catch(() => {})
  }, [load])

  const updateJob = (id: number, patch: Partial<UploadJob>) =>
    setUploads((u) => u.map((j) => (j.id === id ? { ...j, ...patch } : j)))
  const dismissJob = (id: number) => setUploads((u) => u.filter((j) => j.id !== id))

  async function uploadFiles(files: File[]) {
    // Queue every file up front so unsupported ones are reported immediately.
    const jobs = files.map((file) => ({ file, id: ++jobId.current, problem: uploadProblem(file) }))
    setUploads((u) => [
      ...u,
      ...jobs.map(({ file, id, problem }) => ({ id, name: file.name, progress: 0, error: problem ?? undefined })),
    ])
    for (const { file, id, problem } of jobs) {
      if (problem) continue
      try {
        const media = await api.upload(file, (p) => updateJob(id, { progress: p }))
        load()
        if (media.converted_from) {
          updateJob(id, { note: `Uploaded and converted (${media.converted_from})` })
          setTimeout(() => dismissJob(id), 8000)
        } else {
          dismissJob(id)
        }
      } catch (err) {
        updateJob(id, { error: (err as Error).message })
      }
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    const files = droppedFiles(e.dataTransfer)
    if (files.length) uploadFiles(files)
    else setError("Couldn't read the dropped items. In Photos, use File → Export, or click Upload files.")
  }

  async function act(fn: () => Promise<unknown>) {
    setError('')
    try {
      await fn()
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function rename(m: Media) {
    const title = prompt('Rename', m.title)
    if (title && title.trim() && title !== m.title) act(() => api.renameMedia(m.id, title.trim()))
  }

  function remove(m: Media) {
    const warning = m.used_in_loops ? `\n\nIt will also be removed from ${m.used_in_loops} loop(s).` : ''
    if (confirm(`Delete "${m.title}"?${warning}`)) act(() => api.deleteMedia(m.id))
  }

  const shown = filter === 'all' ? media : media.filter((m) => m.status === filter)
  const pendingCount = media.filter((m) => m.status === 'pending').length

  return (
    <div>
      <header className="page-head">
        <h1>Media</h1>
        <div className="head-actions">
          <label className="toggle" title="When off, new uploads wait in the approval queue and won't play until approved.">
            <input
              type="checkbox"
              checked={autoApprove}
              onChange={(e) => api.putSettings(e.target.checked).then((s) => setAutoApprove(s.auto_approve))}
            />
            Auto-approve my uploads
          </label>
          <button onClick={() => setEditing('new')}>+ Text slide</button>
          <button className="primary" onClick={() => fileInput.current?.click()}>Upload files</button>
          <input ref={fileInput} type="file" accept={UPLOAD_ACCEPT} multiple hidden onChange={(e) => {
            if (e.target.files) uploadFiles(Array.from(e.target.files))
            e.target.value = ''
          }} />
        </div>
      </header>

      <div
        className={`dropzone ${dragging ? 'over' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => fileInput.current?.click()}
      >
        Drop photos and videos here, or click to choose files
        <small>JPG, PNG, HEIC, MP4 or MOV · HEIC becomes JPG and MOV becomes MP4 automatically</small>
      </div>

      {uploads.map((u) => (
        <div key={u.id} className={`upload ${u.error ? 'failed' : ''}`}>
          <span>{u.name}</span>
          {u.error ? (
            <>
              <span className="error">{u.error}</span>
              <button className="link" onClick={() => dismissJob(u.id)}>Dismiss</button>
            </>
          ) : u.note ? (
            <span className="ok-text">✓ {u.note}</span>
          ) : u.progress < 1 ? (
            <progress value={u.progress} max={1} />
          ) : (
            <>
              <progress />
              <span className="muted">Processing… large videos can take a minute</span>
            </>
          )}
        </div>
      ))}

      {error && <p className="error">{error}</p>}

      <div className="tabs">
        {FILTERS.map((f) => (
          <button key={f} className={filter === f ? 'active' : ''} onClick={() => setFilter(f)}>
            {f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1)}
            {f === 'pending' && pendingCount > 0 && <span className="badge">{pendingCount}</span>}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="empty">{filter === 'pending' ? 'Nothing waiting for approval.' : 'No media yet. Upload a file or create a text slide.'}</p>
      ) : (
        <div className="media-grid">
          {shown.map((m) => (
            <div key={m.id} className="card media-card">
              <MediaThumb media={m} height={135} />
              <div className="media-meta">
                <strong title={m.title}>{m.title}</strong>
                <div className="muted">
                  <KindTag kind={m.kind} /> {m.kind === 'video' && `${(m.duration_seconds ?? 0).toFixed(1)}s · `}
                  {m.width && m.height ? `${m.width}×${m.height} · ` : ''}
                  {formatBytes(m.size_bytes)}
                </div>
                <div className="muted">
                  <span className={`status status-${m.status}`}>{m.status}</span>
                  {m.used_in_loops > 0 && ` · in ${m.used_in_loops} loop${m.used_in_loops > 1 ? 's' : ''}`}
                </div>
              </div>
              <div className="card-actions">
                {m.status !== 'approved' && <button className="primary small" onClick={() => act(() => api.approve(m.id))}>Approve</button>}
                {m.status !== 'rejected' && m.status === 'pending' && (
                  <button className="small" onClick={() => act(() => api.reject(m.id))}>Reject</button>
                )}
                {m.kind === 'text' ? (
                  <button className="small" onClick={() => setEditing(m)}>Edit</button>
                ) : (
                  <button className="small" onClick={() => rename(m)}>Rename</button>
                )}
                <button className="small danger" onClick={() => remove(m)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <TextSlideEditor
          initial={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            load()
          }}
        />
      )}
    </div>
  )
}
