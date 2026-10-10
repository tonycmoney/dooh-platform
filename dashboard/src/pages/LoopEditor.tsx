import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { api, formatDuration, type Media, type Screen, type VideoFit } from '../api'
import { KindTag, LandscapeWarning, LoopPreview, MediaThumb } from '../components'

const DEFAULT_SECONDS = 10

interface DraftItem {
  key: string
  media: Media
  duration_seconds: number
  video_fit: VideoFit
}

let keySeq = 0
const newKey = () => `k${++keySeq}`

function SortableRow({ item, index, onChange, onRemove }: {
  item: DraftItem
  index: number
  onChange: (patch: Partial<DraftItem>) => void
  onRemove: () => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.key })
  const m = item.media
  const videoLength = m.duration_seconds ?? 0
  return (
    <li
      ref={setNodeRef}
      className={`loop-row ${isDragging ? 'dragging' : ''}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <button className="handle" {...attributes} {...listeners} aria-label="Drag to reorder">⋮⋮</button>
      <span className="pos">{index + 1}</span>
      <MediaThumb media={m} width={34} />
      <div className="loop-row-info">
        <strong>{m.title}</strong>
        <div className="muted">
          <KindTag kind={m.kind} /> <LandscapeWarning media={m} compact />
          {m.kind === 'video' && ` ${videoLength.toFixed(1)}s video`}
          {m.status !== 'approved' && <span className={`status status-${m.status}`}> {m.status}: won't play</span>}
        </div>
      </div>
      <label className="secs">
        <input
          type="number"
          min={1}
          max={3600}
          value={item.duration_seconds}
          onChange={(e) => onChange({ duration_seconds: Math.max(1, Math.min(3600, Number(e.target.value) || 1)) })}
        />
        sec
      </label>
      {m.kind === 'video' ? (
        <div className="fit">
          <select value={item.video_fit} onChange={(e) => onChange({ video_fit: e.target.value as VideoFit })}>
            <option value="loop">Loop to fill time</option>
            <option value="cut">Play once, cut at time</option>
          </select>
          {Math.round(videoLength) !== item.duration_seconds && videoLength > 0 && (
            <button className="link small" onClick={() => onChange({ duration_seconds: Math.max(1, Math.round(videoLength)) })}>
              Use video length ({Math.round(videoLength)}s)
            </button>
          )}
        </div>
      ) : (
        <div className="fit" />
      )}
      <button className="link danger" onClick={onRemove} aria-label="Remove">✕</button>
    </li>
  )
}

export default function LoopEditor() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [items, setItems] = useState<DraftItem[]>([])
  const [library, setLibrary] = useState<Media[]>([])
  const [screens, setScreens] = useState<Screen[]>([])
  const [assigned, setAssigned] = useState<Set<string>>(new Set())
  const [savedAssigned, setSavedAssigned] = useState<Set<string>>(new Set())
  const [dirty, setDirty] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  useEffect(() => {
    Promise.all([api.getLoop(id), api.listMedia(), api.listScreens()])
      .then(([loop, media, screenList]) => {
        setName(loop.name)
        setItems(loop.items.map((i) => ({ key: newKey(), media: i.media, duration_seconds: i.duration_seconds, video_fit: i.video_fit })))
        setLibrary(media.filter((m) => m.status !== 'rejected'))
        setScreens(screenList)
        setAssigned(new Set(loop.device_ids))
        setSavedAssigned(new Set(loop.device_ids))
      })
      .catch((e) => setError(e.message))
  }, [id])

  // Warn before leaving with unsaved changes.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const edit = (fn: (prev: DraftItem[]) => DraftItem[]) => {
    setItems(fn)
    setDirty(true)
    setMessage('')
  }

  function add(media: Media) {
    const seconds = media.kind === 'video' && media.duration_seconds ? Math.max(1, Math.round(media.duration_seconds)) : DEFAULT_SECONDS
    edit((prev) => [...prev, { key: newKey(), media, duration_seconds: media.kind === 'video' ? seconds : DEFAULT_SECONDS, video_fit: 'loop' }])
  }

  function onDragEnd(e: DragEndEvent) {
    const { active, over } = e
    if (!over || active.id === over.id) return
    edit((prev) => {
      const from = prev.findIndex((i) => i.key === active.id)
      const to = prev.findIndex((i) => i.key === over.id)
      return arrayMove(prev, from, to)
    })
  }

  async function save() {
    setError('')
    try {
      await api.saveLoop(
        id,
        name.trim() || 'Untitled loop',
        items.map((i) => ({ media_id: i.media.id, duration_seconds: i.duration_seconds, video_fit: i.video_fit })),
      )
      setDirty(false)
      setMessage(savedAssigned.size ? 'Saved. Assigned screens will update within a minute.' : 'Saved.')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function saveAssignment() {
    setError('')
    try {
      const loop = await api.assignLoop(id, [...assigned])
      setSavedAssigned(new Set(loop.device_ids))
      setScreens(await api.listScreens())
      setMessage('Screens updated. They will switch within a minute.')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function remove() {
    if (!confirm(`Delete loop "${name}"? Screens playing it will go blank.`)) return
    await api.deleteLoop(id)
    navigate('/loops')
  }

  const total = items.reduce((sum, i) => sum + i.duration_seconds, 0)
  const assignmentDirty = useMemo(
    () => assigned.size !== savedAssigned.size || [...assigned].some((x) => !savedAssigned.has(x)),
    [assigned, savedAssigned],
  )
  const filteredLibrary = library.filter((m) => m.title.toLowerCase().includes(search.toLowerCase()))

  return (
    <div>
      <header className="page-head">
        <input
          className="title-input"
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            setDirty(true)
          }}
          aria-label="Loop name"
        />
        <div className="head-actions">
          <span className="muted">{items.length} items · {formatDuration(total)} per cycle</span>
          <button className="danger" onClick={remove}>Delete loop</button>
          <button className="primary" onClick={save} disabled={!dirty}>{dirty ? 'Save loop' : 'Saved'}</button>
        </div>
      </header>
      {message && <p className="notice">{message}</p>}
      {error && <p className="error">{error}</p>}

      <div className="loop-layout">
        <section>
          <h2>Playlist order</h2>
          {items.length === 0 ? (
            <p className="empty">Add media from the library on the right.</p>
          ) : (
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
              <SortableContext items={items.map((i) => i.key)} strategy={verticalListSortingStrategy}>
                <ol className="loop-list">
                  {items.map((item, index) => (
                    <SortableRow
                      key={item.key}
                      item={item}
                      index={index}
                      onChange={(patch) => edit((prev) => prev.map((i) => (i.key === item.key ? { ...i, ...patch } : i)))}
                      onRemove={() => edit((prev) => prev.filter((i) => i.key !== item.key))}
                    />
                  ))}
                </ol>
              </SortableContext>
            </DndContext>
          )}

          <h2>Play on screens</h2>
          {screens.length === 0 ? (
            <p className="empty">No screens paired yet. Pair one on the Screens page.</p>
          ) : (
            <div className="card">
              {screens.map((s) => (
                <label key={s.id} className="check-row">
                  <input
                    type="checkbox"
                    checked={assigned.has(s.id)}
                    onChange={(e) => {
                      const next = new Set(assigned)
                      if (e.target.checked) next.add(s.id)
                      else next.delete(s.id)
                      setAssigned(next)
                    }}
                  />
                  <span className={`dot ${s.online ? 'on' : 'off'}`} />
                  <strong>{s.name}</strong>
                  <span className="muted">{s.venue_name}</span>
                  {s.loop_id && s.loop_id !== id && <span className="muted">(now playing “{s.loop_name}”, will be replaced)</span>}
                </label>
              ))}
              <div className="actions">
                <button className="primary" disabled={!assignmentDirty} onClick={saveAssignment}>
                  Save screen assignment
                </button>
              </div>
            </div>
          )}
        </section>

        <aside>
          <h2>Preview on a portrait screen</h2>
          <LoopPreview items={items} width={220} />
          <h2>Library</h2>
          <input placeholder="Search media" value={search} onChange={(e) => setSearch(e.target.value)} />
          <ul className="library">
            {filteredLibrary.map((m) => (
              <li key={m.id}>
                <MediaThumb media={m} width={24} />
                <span className="lib-title" title={m.title}>
                  {m.title}
                  {m.status === 'pending' && <span className="status status-pending"> pending</span>}
                </span>
                <button className="small" onClick={() => add(m)}>Add</button>
              </li>
            ))}
            {filteredLibrary.length === 0 && <li className="muted">No media. Upload some on the Media page.</li>}
          </ul>
        </aside>
      </div>
    </div>
  )
}
