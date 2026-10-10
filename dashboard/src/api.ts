export type MediaKind = 'image' | 'video' | 'text'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected'
export type VideoFit = 'loop' | 'cut'

export interface Media {
  id: string
  kind: MediaKind
  title: string
  status: ApprovalStatus
  url: string | null
  thumbnail_url: string | null
  original_name: string | null
  size_bytes: number | null
  width: number | null
  height: number | null
  duration_seconds: number | null
  text: string | null
  font_size: number | null
  text_color: string | null
  background_color: string | null
  created_at: string
  used_in_loops: number
  converted_from?: string | null
}

export interface TextSlideInput {
  title: string
  text: string
  font_size: number
  text_color: string
  background_color: string
}

export interface LoopItem {
  id: string
  media_id: string
  position: number
  duration_seconds: number
  video_fit: VideoFit
  media: Media
}

export interface Loop {
  id: string
  name: string
  items: LoopItem[]
  device_ids: string[]
  total_seconds: number
  updated_at: string
}

export interface LoopSummary {
  id: string
  name: string
  item_count: number
  total_seconds: number
  device_count: number
  updated_at: string
}

export interface LoopItemInput {
  media_id: string
  duration_seconds: number
  video_fit: VideoFit
}

export interface Screen {
  id: string
  device_uid: string
  name: string | null
  venue_name: string | null
  venue_address: string | null
  latitude: number | null
  longitude: number | null
  location_accuracy_m: number | null
  location_at: string | null
  online: boolean
  last_seen_at: string | null
  battery_level: number | null
  is_charging: boolean | null
  app_version: string | null
  now_playing_title: string | null
  loop_id: string | null
  loop_name: string | null
  in_sync: boolean
  paired_at: string | null
}

export interface PlayLog {
  id: string
  media_title: string | null
  started_at: string
  duration_ms: number
}

const TOKEN_KEY = 'dooh-admin-token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable: stay logged in for this tab only */
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown })?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`).join('; ')
  }
  return fallback
}

let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401 && !path.endsWith('/login')) onUnauthorized()
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new ApiError(res.status, errorMessage(data, `${res.status} ${res.statusText}`))
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const UPLOAD_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.heic', '.heif', '.mp4', '.mov']
export const UPLOAD_ACCEPT = [
  ...UPLOAD_EXTENSIONS,
  'image/jpeg',
  'image/png',
  'image/heic',
  'image/heif',
  'video/mp4',
  'video/quicktime',
].join(',')

/** Returns a user-facing reason if this file can't be uploaded, else null. */
export function uploadProblem(file: File): string | null {
  const dot = file.name.lastIndexOf('.')
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!UPLOAD_EXTENSIONS.includes(ext)) {
    const type = ext ? ext.slice(1).toUpperCase() : 'This file type'
    return `${type} isn't supported. Upload JPG, PNG, HEIC, MP4 or MOV.`
  }
  if (file.size === 0) {
    return "The file is empty. If it's in iCloud, open it in Photos to download it first, or use File → Export."
  }
  return null
}

/** Uploads the file as the raw request body (no multipart form), with
 * progress. The server converts HEIC → JPG and MOV → MP4, which happens after
 * the bytes are sent, so onProgress reports 1 and then the promise waits. */
function upload(file: File, onProgress: (fraction: number) => void): Promise<Media> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/admin/media')
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream')
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name))
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.upload.onload = () => onProgress(1)
    xhr.onload = () => {
      let data: unknown = null
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        /* non-JSON error */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as Media)
      else {
        if (xhr.status === 401) onUnauthorized()
        reject(new ApiError(xhr.status, errorMessage(data, `Upload failed (${xhr.status})`)))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'Network error during upload. Is the server running?'))
    xhr.send(file)
  })
}

export const api = {
  login: (password: string) => request<{ token: string }>('POST', '/api/admin/login', { password }),
  stats: () => request<{ pending_approvals: number; plays_today: number }>('GET', '/api/admin/stats'),
  getSettings: () => request<{ auto_approve: boolean }>('GET', '/api/admin/settings'),
  putSettings: (auto_approve: boolean) =>
    request<{ auto_approve: boolean }>('PUT', '/api/admin/settings', { auto_approve }),

  listMedia: (status?: ApprovalStatus) =>
    request<Media[]>('GET', `/api/admin/media${status ? `?status=${status}` : ''}`),
  upload,
  createTextSlide: (body: TextSlideInput) => request<Media>('POST', '/api/admin/text-slides', body),
  updateTextSlide: (id: string, body: TextSlideInput) =>
    request<Media>('PUT', `/api/admin/text-slides/${id}`, body),
  renameMedia: (id: string, title: string) => request<Media>('PATCH', `/api/admin/media/${id}`, { title }),
  approve: (id: string) => request<Media>('POST', `/api/admin/media/${id}/approve`),
  reject: (id: string) => request<Media>('POST', `/api/admin/media/${id}/reject`),
  deleteMedia: (id: string) => request<void>('DELETE', `/api/admin/media/${id}`),

  listLoops: () => request<LoopSummary[]>('GET', '/api/admin/loops'),
  getLoop: (id: string) => request<Loop>('GET', `/api/admin/loops/${id}`),
  createLoop: (name: string) => request<Loop>('POST', '/api/admin/loops', { name, items: [] }),
  saveLoop: (id: string, name: string, items: LoopItemInput[]) =>
    request<Loop>('PUT', `/api/admin/loops/${id}`, { name, items }),
  deleteLoop: (id: string) => request<void>('DELETE', `/api/admin/loops/${id}`),
  assignLoop: (id: string, device_ids: string[]) =>
    request<Loop>('PUT', `/api/admin/loops/${id}/screens`, { device_ids }),

  listScreens: () => request<Screen[]>('GET', '/api/admin/screens'),
  pairScreen: (body: {
    pairing_code: string
    name: string
    venue_name: string
    venue_address: string
    loop_id?: string | null
  }) => request<Screen>('POST', '/api/admin/screens/pair', body),
  updateScreen: (
    id: string,
    body: Partial<{ name: string; venue_name: string; venue_address: string; loop_id: string; clear_loop: boolean }>,
  ) => request<Screen>('PATCH', `/api/admin/screens/${id}`, body),
  unpairScreen: (id: string) => request<void>('DELETE', `/api/admin/screens/${id}`),
  screenPlays: (id: string) => request<PlayLog[]>('GET', `/api/admin/screens/${id}/plays?limit=20`),
}

// --- Formatting helpers -------------------------------------------------------

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`
}

export function formatBytes(bytes: number | null): string {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`
}

export function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return new Date(iso).toLocaleString()
}
