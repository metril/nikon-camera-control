import { fileUrl } from '@/api'

export function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`
}

/** `ts` is epoch seconds (number) or an ISO string. */
export function formatDate(ts) {
  if (ts == null || ts === '') return '-'
  const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDuration(s) {
  if (!Number.isFinite(s)) return '-'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`
}

export const kindTone = (kind) => ({ raw: 'warn', video: 'accent' })[kind] || 'neutral'

/**
 * Resolve a file URL usable by <img>/<video>. The session cookie authenticates plain URLs, so this
 * is just the URL. Call `release()` when done (a no-op, kept so callers need not care).
 */
export const resolveFile = async (path) => ({ url: fileUrl(path), release() {} })

const SYSTEM_FOLDERS = new Set(['system volume information', '$recycle.bin', 'lost+found'])
/** OS/system folders (and any dot-folder) never belong in the gallery's folder chips. */
export const isSystemFolder = (name) =>
  name.startsWith('.') || SYSTEM_FOLDERS.has(name.toLowerCase())
