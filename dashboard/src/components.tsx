import { useEffect, useState, type ReactNode } from 'react'
import type { Media } from './api'
import { CANVAS_WIDTH, PORTRAIT, RECOMMENDED_SIZE, isLandscape, needsBars } from './portrait'

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
  if (media.kind === 'text') {
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
  if (!isLandscape(media)) return null
  return compact ? (
    <span className="warn-tag" title={`Landscape (${media.width}×${media.height}). Shows with blurred bars on portrait screens. Recommended: ${RECOMMENDED_SIZE}.`}>
      ⚠ landscape
    </span>
  ) : (
    <div className="warn">
      ⚠ Landscape ({media.width}×{media.height}). It will play centered with blurred bars above and below. For a
      full-screen ad, use {RECOMMENDED_SIZE} px portrait.
    </div>
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
  if (m.kind === 'text') {
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
