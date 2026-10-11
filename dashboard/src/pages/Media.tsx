import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react'
import { UPLOAD_ACCEPT, api, formatBytes, uploadProblem, type ApprovalStatus, type Media, type TextSlideInput } from '../api'
import { FitModeSelect, FormatPreview, KindTag, LandscapeWarning, MediaThumb, Modal } from '../components'
import { RECOMMENDED_SIZE, isLandscape } from '../portrait'

interface UploadJob {
  id: number
  name: string
  progress: number
  error?: string
  note?: string
  warning?: string
  media?: Media
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
  const [preview, setPreview] = useState<string | null>(null)
  const set = <K extends keyof TextSlideInput>(key: K, value: TextSlideInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  // The server renders the slide (same picture the screens get), shortly
  // after typing stops.
  const { text, text_color, background_color } = form
  useEffect(() => {
    if (!text.trim()) return
    const abort = new AbortController()
    let url: string | null = null
    const timer = setTimeout(() => {
      api
        .previewTextSlide({ title: 'preview', text, font_size: 96, text_color, background_color }, abort.signal)
        .then((u) => {
          url = u
          setPreview(u)
        })
        .catch(() => {})
    }, 350)
    return () => {
      clearTimeout(timer)
      abort.abort()
      if (url) setTimeout(() => URL.revokeObjectURL(url!), 1000)
    }
  }, [text, text_color, background_color])

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
    <Modal title={initial ? 'Edit text slide' : 'New text slide'} onClose={onClose} wide>
      <form className="slide-editor" onSubmit={submit}>
        <div className="slide-preview-col">
          <div className="frame" style={{ width: 234, height: 416 }}>
            {preview && form.text.trim() ? (
              <img className="frame-content" src={preview} alt="Slide preview" />
            ) : (
              <span className="frame-label">Type some text</span>
            )}
          </div>
          <span className="muted small-text">Exactly as screens show it: 1080 × 1920, white border</span>
        </div>
        <div className="slide-fields">
        <label>
          Title (for your list)
          <input value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Happy hour promo" />
        </label>
        <label>
          Text on screen
          <textarea rows={5} value={form.text} onChange={(e) => set('text', e.target.value)} required />
        </label>
        <p className="muted small-text">The text is sized automatically to fill the slide.</p>
        <div className="row">
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
  const [previewing, setPreviewing] = useState<Media | null>(null)
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
        const note = `Formatted to ${RECOMMENDED_SIZE} · ${media.format_note ?? ''}`
        if (isLandscape(media)) {
          // Stays until dismissed: the user may want Fill or a portrait version.
          updateJob(id, {
            note,
            media,
            warning: 'Landscape: shown whole over a blurred background. Preview it, or choose Fill to crop.',
          })
        } else {
          updateJob(id, { note, media })
          setTimeout(() => dismissJob(id), 10000)
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
        <strong className="recommended">Recommended ad size: {RECOMMENDED_SIZE} px (portrait, 9:16)</strong>
        <small>
          JPG, PNG, HEIC, MP4 or MOV · each upload is formatted to {RECOMMENDED_SIZE} with a thin white border ·
          other shapes are shown whole over a blurred background · the original is kept
        </small>
      </div>

      {uploads.map((u) => (
        <div key={u.id} className={`upload ${u.error ? 'failed' : ''}`}>
          <span>{u.name}</span>
          {u.error ? (
            <>
              <span className="error">{u.error}</span>
              <button className="link" onClick={() => dismissJob(u.id)}>Dismiss</button>
            </>
          ) : u.warning ? (
            <>
              <span className="ok-text">✓ {u.note}</span>
              <span className="warn-inline">⚠ {u.warning}</span>
              {u.media && <button className="link" onClick={() => setPreviewing(u.media!)}>Preview</button>}
              <button className="link" onClick={() => dismissJob(u.id)}>Dismiss</button>
            </>
          ) : u.note ? (
            <>
              <span className="ok-text">✓ {u.note}</span>
              {u.media && <button className="link" onClick={() => setPreviewing(u.media!)}>Preview</button>}
            </>
          ) : u.progress < 1 ? (
            <progress value={u.progress} max={1} />
          ) : (
            <>
              <progress />
              <span className="muted">Formatting… videos can take a minute or two</span>
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
              <button className="card-frame" onClick={() => setPreviewing(m)} title="Preview as screens show it">
                <MediaThumb media={m} width={135} />
              </button>
              <div className="media-meta">
                <strong title={m.title}>{m.title}</strong>
                <div className="muted">
                  <KindTag kind={m.kind} /> {m.kind === 'video' && `${(m.duration_seconds ?? 0).toFixed(1)}s · `}
                  {m.source_width && m.source_height ? `original ${m.source_width}×${m.source_height} · ` : ''}
                  {formatBytes(m.size_bytes)}
                </div>
                <div className="muted">
                  <span className={`status status-${m.status}`}>{m.status}</span> <LandscapeWarning media={m} compact />
                  {m.used_in_loops > 0 && ` · in ${m.used_in_loops} loop${m.used_in_loops > 1 ? 's' : ''}`}
                </div>
                <FitModeSelect media={m} onChanged={() => load()} />
              </div>
              <div className="card-actions">
                {m.status !== 'approved' && <button className="primary small" onClick={() => act(() => api.approve(m.id))}>Approve</button>}
                {m.status !== 'rejected' && m.status === 'pending' && (
                  <button className="small" onClick={() => act(() => api.reject(m.id))}>Reject</button>
                )}
                <button className="small" onClick={() => setPreviewing(m)}>Preview</button>
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

      {previewing && (
        <FormatPreview
          media={media.find((m) => m.id === previewing.id) ?? previewing}
          onClose={() => setPreviewing(null)}
          onChanged={(m) => {
            setPreviewing(m)
            load()
          }}
        />
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
