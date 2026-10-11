import type { Media } from './api'

/** Every item is formatted on the server to 1080 x 1920 with a 12 px white
 * border, so previews show the formatted file in a 9:16 frame. */
export const CANVAS_WIDTH = 1080
export const CANVAS_HEIGHT = 1920
export const BORDER_PX = 12
export const RECOMMENDED_SIZE = '1080 × 1920'
export const PORTRAIT = CANVAS_WIDTH / CANVAS_HEIGHT

/** The original's size (falls back to the stored size for older items). */
function originalSize(m: Pick<Media, 'width' | 'height' | 'source_width' | 'source_height'>) {
  return { w: m.source_width ?? m.width, h: m.source_height ?? m.height }
}

export function isLandscape(m: Pick<Media, 'width' | 'height' | 'source_width' | 'source_height'>): boolean {
  const { w, h } = originalSize(m)
  return !!w && !!h && w > h
}

/** True when the stored file isn't 9:16 (only items not yet formatted). */
export function needsBars(m: Pick<Media, 'width' | 'height' | 'kind'>): boolean {
  if (!m.width || !m.height) return false
  return Math.abs(m.width / m.height - PORTRAIT) / PORTRAIT > 0.03
}
