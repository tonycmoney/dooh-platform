import type { Media } from './api'

/** Screens are portrait. Text slides are designed on a 1080 x 1920 canvas and
 * scaled to the screen's width, on the tablet and in these previews alike. */
export const CANVAS_WIDTH = 1080
export const CANVAS_HEIGHT = 1920
export const RECOMMENDED_SIZE = '1080 × 1920'
export const PORTRAIT = CANVAS_WIDTH / CANVAS_HEIGHT

export function isLandscape(m: Pick<Media, 'width' | 'height'>): boolean {
  return !!m.width && !!m.height && m.width > m.height
}

/** True when the item won't fill a 9:16 screen and will get blurred bars. */
export function needsBars(m: Pick<Media, 'width' | 'height' | 'kind'>): boolean {
  if (m.kind === 'text' || !m.width || !m.height) return false
  return Math.abs(m.width / m.height - PORTRAIT) / PORTRAIT > 0.03
}
