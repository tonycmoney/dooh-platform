import { useEffect, type ReactNode } from 'react'
import type { Media } from './api'

/** Text slides are designed on a 1080-px-tall canvas; the tablet scales them
 * to its own height, and so does this preview. */
export const TEXT_CANVAS_HEIGHT = 1080

export function TextSlidePreview({
  text,
  fontSize,
  textColor,
  backgroundColor,
  height,
}: {
  text: string
  fontSize: number
  textColor: string
  backgroundColor: string
  height: number
}) {
  const scale = height / TEXT_CANVAS_HEIGHT
  return (
    <div
      className="text-slide"
      style={{
        height,
        width: (height * 16) / 10,
        background: backgroundColor,
        color: textColor,
        fontSize: fontSize * scale,
        padding: 48 * scale,
      }}
    >
      {text || ' '}
    </div>
  )
}

export function MediaThumb({ media, height = 54 }: { media: Media; height?: number }) {
  if (media.kind === 'text') {
    return (
      <TextSlidePreview
        text={media.text ?? ''}
        fontSize={media.font_size ?? 96}
        textColor={media.text_color ?? '#FFFFFF'}
        backgroundColor={media.background_color ?? '#000000'}
        height={height}
      />
    )
  }
  return (
    <div className="thumb" style={{ height, width: (height * 16) / 10 }}>
      {media.thumbnail_url ? <img src={media.thumbnail_url} alt="" /> : <span>{media.kind}</span>}
      {media.kind === 'video' && <span className="thumb-tag">▶ {Math.round(media.duration_seconds ?? 0)}s</span>}
    </div>
  )
}

export function KindTag({ kind }: { kind: Media['kind'] }) {
  return <span className={`tag tag-${kind}`}>{kind}</span>
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal card" role="dialog" aria-label={title}>
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
