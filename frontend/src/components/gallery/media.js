import { api, fileUrl, videoUrl } from '@/api'
import { useAuthStore } from '@/stores/auth'

export function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '--'
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
  if (ts == null || ts === '') return '--'
  const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
  if (Number.isNaN(d.getTime())) return '--'
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDuration(s) {
  if (!Number.isFinite(s)) return '--'
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.round(s % 60)).padStart(2, '0')}`
}

export const kindTone = (kind) =>
  ({ raw: 'warn', video: 'info', image: 'neutral' })[kind] || 'neutral'

/**
 * Resolve a media URL usable by <img>/<video>. Without an API key it is the plain URL; with one
 * the file is fetched as a blob (headers) and exposed as an object URL. Call `release()` when done.
 */
async function resolve(plain, fetchBlob) {
  if (!useAuthStore().apiKey) return { url: plain, release() {} }
  const url = URL.createObjectURL(await fetchBlob())
  return { url, release: () => URL.revokeObjectURL(url) }
}
export const resolveFile = (path) =>
  resolve(fileUrl(path), () => api.downloadFile({ path: { path }, parseAs: 'blob' }))
export const resolveVideo = (sessionId, name) =>
  resolve(videoUrl(sessionId, name), () =>
    api.downloadVideo({ path: { session_id: sessionId, name }, parseAs: 'blob' }),
  )
