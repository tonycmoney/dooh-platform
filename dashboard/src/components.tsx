import { useEffect, useState, type ReactNode } from 'react'
import { api, type FitMode, type Media } from './api'
import { BORDER_PX, CANVAS_WIDTH, PORTRAIT, RECOMMENDED_SIZE, isLandscape, needsBars } from './portrait'

export function TextSlidePreview({
  text,
  fontSize,
  textColor,
  backgroundColor,
  width,
}: {
  text: string
  fontSize: number
  textColor: string
  backgroundColor: string
  width: number
}) {
  const scale = width / CANVAS_WIDTH
  return (
    <div
      className="text-slide"
      style={{
        width,
        height: width / PORTRAIT,
        background: backgroundColor,
        color: textColor,
        fontSize: fontSize * scale,
        padding: `${160 * scale}px ${90 * scale}px`,
        letterSpacing: `${-0.01 * fontSize * scale}px`,
      }}
    >
      {text || ' '}
    </div>
  )
}

/** A 9:16 frame that shows an image or video the way the tablet will: filling
 * the frame if it's portrait, or centered over blurred bars if it isn't. */
function PortraitFrame({ src, width, children }: { src: string | null; width: number; children: ReactNode }) {
  return (
    <div className="frame" style={{ width, height: width / PORTRAIT }}>
      {src && <div className="frame-blur" style={{ backgroundImage: `url("${src}")` }} />}
      {children}
    </div>
  )
}

export function MediaThumb({ media, width = 30 }: { media: Media; width?: number }) {
  if (media.kind === 'text' && !media.thumbnail_url) {
    return (
      <TextSlidePreview
        text={media.text ?? ''}
        fontSize={media.font_size ?? 96}
        textColor={media.text_color ?? '#FFFFFF'}
        backgroundColor={media.background_color ?? '#000000'}
        width={width}
      />
    )
  }
  const src = media.thumbnail_url
  return (
    <PortraitFrame src={needsBars(media) ? src : null} width={width}>
      {src ? <img src={src} alt="" className="frame-content" /> : <span className="frame-label">{media.kind}</span>}
      {media.kind === 'video' && width >= 60 && (
        <span className="thumb-tag">▶ {Math.round(media.duration_seconds ?? 0)}s</span>
      )}
    </PortraitFrame>
  )
}

export function KindTag({ kind }: { kind: Media['kind'] }) {
  return <span className={`tag tag-${kind}`}>{kind}</span>
}

export function LandscapeWarning({ media, compact = false }: { media: Media; compact?: boolean }) {
  if (media.kind === 'text' || !isLandscape(media) || media.fit_mode === 'fill') return null
  const size = `${media.source_width ?? media.width}×${media.source_height ?? media.height}`
  return compact ? (
    <span className="warn-tag" title={`Landscape original (${size}): shown whole over a blurred background. Choose Fill to crop it to the screen, or upload ${RECOMMENDED_SIZE} px.`}>
      ⚠ landscape
    </span>
  ) : (
    <div className="warn">
      ⚠ Landscape original ({size}). It's shown whole in the middle of the screen over a blurred background. For a
      full-screen ad, upload {RECOMMENDED_SIZE} px portrait, or choose Fill if cropping the sides is fine.
    </div>
  )
}

const FIT_LABELS: Record<FitMode, string> = {
  fit: 'Fit (show everything)',
  fill: 'Fill (crop edges)',
}

/** Fit/Fill for an image or video. Changing it reformats the item on the server. */
export function FitModeSelect({ media, onChanged }: { media: Media; onChanged: (m: Media) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (media.kind === 'text') return null

  async function change(mode: FitMode) {
    setBusy(true)
    setError('')
    try {
      onChanged(await api.setFitMode(media.id, mode))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="fit-select">
      <select value={media.fit_mode} disabled={busy} onChange={(e) => change(e.target.value as FitMode)}
        aria-label="How the item fills the screen">
        {(Object.keys(FIT_LABELS) as FitMode[]).map((mode) => (
          <option key={mode} value={mode}>{FIT_LABELS[mode]}</option>
        ))}
      </select>
      {busy && <span className="muted small-text">Reformatting{media.kind === 'video' ? ' (videos take a minute)' : ''}…</span>}
      {error && <span className="error small-text">{error}</span>}
    </span>
  )
}

/** The formatted file exactly as screens will play it, with its Fit/Fill
 * option, so an item can be checked before it goes into a loop. */
export function FormatPreview({ media, onChanged, onClose }: {
  media: Media
  onChanged: (m: Media) => void
  onClose: () => void
}) {
  const width = 270
  const src = media.url ?? media.thumbnail_url
  return (
    <Modal title={media.title} onClose={onClose} wide>
      <div className="format-preview">
        <div className="frame" style={{ width, height: width / PORTRAIT }}>
          {media.kind === 'video' && media.url ? (
            <video key={media.url} className="frame-content" src={media.url} autoPlay muted loop playsInline controls />
          ) : src ? (
            <img key={src} className="frame-content" src={src} alt="" />
          ) : (
            <MediaThumb media={media} width={width} />
          )}
        </div>
        <div className="format-preview-info">
          <p>
            <strong>As screens show it:</strong> {CANVAS_WIDTH} × {CANVAS_WIDTH / PORTRAIT} px with a {BORDER_PX} px
            white border.
          </p>
          {media.format_note && <p className="muted">{media.format_note}</p>}
          {media.kind !== 'text' && (
            <>
              <label>
                Screen fit
                <FitModeSelect media={media} onChanged={onChanged} />
              </label>
              <p className="muted small-text">
                Fit shows the whole picture and fills the leftover space with a blurred copy, so no text is ever cut
                off. Fill covers the screen and crops the edges. Use it only for photos where cropping is fine.
              </p>
            </>
          )}
          <LandscapeWarning media={media} />
          {media.status !== 'approved' && (
            <p className={`status status-${media.status}`}>
              {media.status === 'pending' ? "Waiting for approval: it won't play until approved." : "Rejected: it won't play."}
            </p>
          )}
        </div>
      </div>
    </Modal>
  )
}

interface PreviewItem {
  key: string
  media: Media
  duration_seconds: number
}

/** Plays a loop in a 9:16 frame, item by item, with each item's duration. */
export function LoopPreview({ items, width = 220 }: { items: PreviewItem[]; width?: number }) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const current = items.length ? items[index % items.length] : null

  useEffect(() => {
    if (!current || !playing) return
    const timer = setTimeout(() => setIndex((i) => (i + 1) % items.length), current.duration_seconds * 1000)
    return () => clearTimeout(timer)
  }, [current, playing, items.length, index])

  if (!current) {
    return (
      <div className="frame frame-empty" style={{ width, height: width / PORTRAIT }}>
        Empty loop
      </div>
    )
  }
  const m = current.media
  let content: ReactNode
  if (m.kind === 'text' && !m.url) {
    content = <MediaThumb media={m} width={width} />
  } else {
    content = (
      <PortraitFrame src={needsBars(m) ? m.thumbnail_url : null} width={width}>
        {m.kind === 'video' && m.url ? (
          <video key={current.key} className="frame-content" src={m.url} autoPlay muted loop playsInline />
        ) : (
          <img className="frame-content" src={m.url ?? m.thumbnail_url ?? ''} alt="" />
        )}
      </PortraitFrame>
    )
  }
  return (
    <div className="loop-preview">
      {content}
      <div className="loop-preview-bar">
        <button className="link small" onClick={() => setPlaying((p) => !p)}>{playing ? '❚❚ Pause' : '▶ Play'}</button>
        <span className="muted">
          {(index % items.length) + 1}/{items.length} · {m.title} · {current.duration_seconds}s
        </span>
      </div>
    </div>
  )
}

export function Modal({ title, onClose, children, wide = false }: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal card ${wide ? 'modal-wide' : ''}`} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="link" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
