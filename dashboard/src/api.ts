export type MediaKind = 'image' | 'video' | 'text'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected'
export type VideoFit = 'loop' | 'cut'
export type FitMode = 'fit' | 'fill'

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
  fit_mode: FitMode
  /** Size of the original upload (width/height are the formatted 1080×1920). */
  source_width: number | null
  source_height: number | null
  /** How the original was formatted, e.g. "Landscape 1600×900: shown whole over a blurred background". */
  format_note: string | null
  created_at: string
  used_in_loops: number
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

export interface Backup {
  name: string
  size_bytes: number
  created_at: string
}

export interface BackupList {
  daily_enabled: boolean
  keep_days: number
  backups: Backup[]
}

export type FileStatus = 'none' | 'queued' | 'ready' | 'failed'

/** An ad order from the customer website. */
export interface Order {
  id: string
  external_id: string
  business_name: string
  contact_name: string | null
  email: string
  phone: string | null
  plan: string
  plan_name: string | null
  city: string | null
  ad_choice: string | null
  ad_text: string | null
  notes: string | null
  file_name: string | null
  file_status: FileStatus
  file_error: string | null
  can_retry: boolean
  media: Media | null
  created_at: string
}

export type AlertKind = 'offline' | 'not_playing'

export interface AdPlays {
  title: string
  plays: number
  seconds: number
  screens: number | null
}

export interface Incident {
  kind: AlertKind
  detail: string | null
  started_at: string
  resolved_at: string | null
  minutes: number
}

export interface ScreenReport {
  device_id: string
  name: string
  venue_name: string | null
  uptime_percent: number | null
  online_minutes: number
  plays: number
  ads: AdPlays[]
  incidents: Incident[]
}

export interface DailyReport {
  day: string
  timezone: string
  screens: ScreenReport[]
  ads: AdPlays[]
  total_plays: number
}

export interface AlertRow {
  id: string
  screen: string
  kind: AlertKind
  detail: string | null
  started_at: string
  resolved_at: string | null
  emailed: boolean
}

export interface MonitoringStatus {
  monitoring: boolean
  email_configured: boolean
  alert_email_to: string[]
  offline_minutes: number
  not_playing_minutes: number
  report_hour: number
  timezone: string
}

export interface Settings {
  auto_approve: boolean
  maintenance_pin_set: boolean
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
  return uploadTo<Media>('/api/admin/media', file, onProgress)
}

function uploadTo<T>(path: string, file: File, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
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
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T)
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
  stats: () =>
    request<{ pending_approvals: number; plays_today: number; orders_to_review: number }>('GET', '/api/admin/stats'),
  listOrders: () => request<Order[]>('GET', '/api/admin/orders'),
  deleteOrder: (id: string) => request<void>('DELETE', `/api/admin/orders/${id}`),
  retryOrderFile: (id: string) => request<Order>('POST', `/api/admin/orders/${id}/retry`),
  attachOrderFile: (id: string, file: File) => uploadTo<Order>(`/api/admin/orders/${id}/file`, file, () => {}),
  getSettings: () => request<Settings>('GET', '/api/admin/settings'),
  putSettings: (auto_approve: boolean) => request<Settings>('PUT', '/api/admin/settings', { auto_approve }),
  setMaintenancePin: (pin: string) => request<Settings>('PUT', '/api/admin/maintenance-pin', { pin }),
  clearMaintenancePin: () => request<Settings>('DELETE', '/api/admin/maintenance-pin'),

  listMedia: (status?: ApprovalStatus) =>
    request<Media[]>('GET', `/api/admin/media${status ? `?status=${status}` : ''}`),
  upload,
  createTextSlide: (body: TextSlideInput) => request<Media>('POST', '/api/admin/text-slides', body),
  updateTextSlide: (id: string, body: TextSlideInput) =>
    request<Media>('PUT', `/api/admin/text-slides/${id}`, body),
  renameMedia: (id: string, title: string) => request<Media>('PATCH', `/api/admin/media/${id}`, { title }),
  /** Switching Fit/Fill makes a new formatted file on the server (videos take a while). */
  setFitMode: (id: string, fit_mode: FitMode) => request<Media>('PATCH', `/api/admin/media/${id}`, { fit_mode }),
  previewTextSlide,
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
    replaces_device_id?: string | null
  }) => request<Screen>('POST', '/api/admin/screens/pair', body),
  updateScreen: (
    id: string,
    body: Partial<{ name: string; venue_name: string; venue_address: string; loop_id: string; clear_loop: boolean }>,
  ) => request<Screen>('PATCH', `/api/admin/screens/${id}`, body),
  unpairScreen: (id: string) => request<void>('DELETE', `/api/admin/screens/${id}`),
  screenPlays: (id: string) => request<PlayLog[]>('GET', `/api/admin/screens/${id}/plays?limit=20`),

  monitoring: () => request<MonitoringStatus>('GET', '/api/admin/monitoring'),
  listAlerts: () => request<AlertRow[]>('GET', '/api/admin/alerts?limit=30'),
  testEmail: () => request<{ sent_to: string[] }>('POST', '/api/admin/alerts/test-email'),
  dailyReport: (day?: string) => request<DailyReport>('GET', `/api/admin/reports/daily${day ? `?day=${day}` : ''}`),
  emailReport: (day: string) => request<{ sent_to: string[] }>('POST', `/api/admin/reports/daily/email?day=${day}`),

  listBackups: () => request<BackupList>('GET', '/api/admin/backups'),
  backupNow: () => request<Backup>('POST', '/api/admin/backups'),
  downloadBackup,
}

/** The exact 1080×1920 picture a text slide will be, as an object URL
 * (revoke it when done). */
async function previewTextSlide(body: TextSlideInput, signal?: AbortSignal): Promise<string> {
  const token = getToken()
  const res = await fetch('/api/admin/text-slides/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
    signal,
  })
  if (res.status === 401) onUnauthorized()
  if (!res.ok) throw new ApiError(res.status, `Preview failed (${res.status})`)
  return URL.createObjectURL(await res.blob())
}

/** Saves a backup file to the computer (the download needs the login token,
 * so it goes through fetch rather than a plain link). */
async function downloadBackup(name: string): Promise<void> {
  const token = getToken()
  const res = await fetch(`/api/admin/backups/${encodeURIComponent(name)}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (res.status === 401) onUnauthorized()
  if (!res.ok) throw new ApiError(res.status, `Download failed (${res.status})`)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
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
