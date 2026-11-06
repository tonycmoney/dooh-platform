import type { Media } from './api'

/** Every item is formatted on the server to 1200 x 1920 (10:16, the
 * tablets' shape), edge to edge with no border, so previews show the
 * formatted file in a 10:16 frame. */
export const CANVAS_WIDTH = 1200
export const CANVAS_HEIGHT = 1920
export const RECOMMENDED_SIZE = '1200 × 1920'
export const PORTRAIT = CANVAS_WIDTH / CANVAS_HEIGHT

/** The original's size (falls back to the stored size for older items). */
function originalSize(m: Pick<Media, 'width' | 'height' | 'source_width' | 'source_height'>) {
  return { w: m.source_width ?? m.width, h: m.source_height ?? m.height }
}

export function isLandscape(m: Pick<Media, 'width' | 'height' | 'source_width' | 'source_height'>): boolean {
  const { w, h } = originalSize(m)
  return !!w && !!h && w > h
}

/** True when the stored file isn't 10:16 (only items not yet formatted). */
export function needsBars(m: Pick<Media, 'width' | 'height' | 'kind'>): boolean {
  if (!m.width || !m.height) return false
  return Math.abs(m.width / m.height - PORTRAIT) / PORTRAIT > 0.03
}
