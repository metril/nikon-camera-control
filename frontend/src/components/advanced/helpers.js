import { computed } from 'vue'
import { useJobsStore } from '@/stores/jobs'

export const ACTIVE_JOB = ['queued', 'pending', 'running']

/** Reactive job (from the jobs store, kept current by events) for a ref holding a job id. */
export function useJob(idRef) {
  const jobs = useJobsStore()
  const job = computed(() => (idRef.value ? jobs.byId[idRef.value] || null : null))
  const running = computed(() => !!job.value && ACTIVE_JOB.includes(job.value.status))
  return { job, running }
}

export const finite = (n) => typeof n === 'number' && Number.isFinite(n)

export function readJson(key, fallback) {
  try {
    const v = JSON.parse(localStorage.getItem(key))
    return v && typeof v === 'object' ? { ...fallback, ...v } : fallback
  } catch {
    return fallback
  }
}
export function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable */
  }
}

export const fmtDuration = (s) => {
  const t = Math.max(0, Math.round(s || 0))
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = t % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(sec).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`
}

/** Validate a focus-stack request against the camera's drive range (mirrors the backend). */
export function stackIssue({ steps, shots, direction }, range) {
  if (!Number.isInteger(steps) || steps < 1 || steps > 32767)
    return 'Steps per shot must be 1-32767'
  if (!Number.isInteger(shots) || shots < 2 || shots > 200) return 'Shots must be 2-200'
  if (range) {
    const delta = direction === 'far_to_near' ? -steps : steps
    if (delta < range.min || delta > range.max)
      return `Steps per shot must stay within ${range.min} to ${range.max}`
    if ((delta - range.min) % range.step)
      return `Steps per shot must be a multiple of ${range.step}`
  }
  return ''
}

/** e.g. 5 shots at 1 EV -> ['-2','-1','0','1','2'] (values for a quick bracketing `exposure` list). */
export function evSeries(shots, ev) {
  const half = (shots - 1) / 2
  return Array.from({ length: shots }, (_, i) => String((i - half) * ev))
}
