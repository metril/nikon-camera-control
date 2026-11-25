import { api } from '@/api'
import { BlobUrlLru } from '@/stores/thumbnailCache'
import { acquireCameraThumb } from './cameraThumbs'

// Rendering a preview reads the whole file over USB: one at a time, the viewed file first.
// A started read cannot be interrupted on the camera, so its slot is held until the server
// answers (abandoning it only rejects the waiter); stale queued files are simply dropped.
const cache = new BlobUrlLru(8)
const inflight = new Map() // key -> { promise, started, aborted, resolve, reject, run, params }
const waiting = [] // keys not started yet
let running = 0
/** Cache key of one card file; size and mtime tell apart a reused name after a card swap. */
export const previewKey = (folder, name, size = 0, mtime = 0) =>
  `${folder}/${name}|${size}|${mtime}`

function pump() {
  while (running < 1 && waiting.length) {
    const key = waiting.shift()
    const job = inflight.get(key)
    if (!job) continue
    running++
    job.started = true
    job.run().finally(() => {
      running--
      inflight.delete(key)
      pump()
    })
  }
}

function waiter(job) {
  job.aborted = false
  job.promise = new Promise((resolve, reject) => {
    job.resolve = resolve
    job.reject = reject
  })
  job.promise.catch(() => {}) // a prefetch nobody awaits must not be an unhandled rejection
}

function enqueue(folder, name, size, mtime, prio) {
  const key = previewKey(folder, name, size, mtime)
  const known = inflight.get(key)
  if (known) {
    if (known.aborted) waiter(known) // wanted again while its read is still on the camera
    if (prio === 0 && !known.started) {
      // the viewed file overtakes queued prefetches
      const i = waiting.indexOf(key)
      if (i > 0) waiting.unshift(...waiting.splice(i, 1))
    }
    return known.promise
  }
  const job = { started: false }
  waiter(job)
  job.run = () =>
    api.getCameraPreview({ query: { folder, name, size, mtime }, parseAs: 'blob' }).then(
      (blob) => {
        if (!cache.has(key)) cache.set(key, URL.createObjectURL(blob))
        if (!job.aborted) job.resolve()
      },
      (e) => {
        if (!job.aborted) job.reject(e)
      },
    )
  inflight.set(key, job)
  if (prio === 0) waiting.unshift(key)
  else waiting.push(key)
  pump()
  return job.promise
}

function abort(key) {
  const job = inflight.get(key)
  if (!job || job.aborted) return
  job.aborted = true
  job.reject(new DOMException('Preview request cancelled', 'AbortError'))
  if (!job.started) {
    const i = waiting.indexOf(key)
    if (i >= 0) waiting.splice(i, 1)
    inflight.delete(key)
  }
}

/** `{ url, release }` of the screen-sized preview (blob so the API key is sent). */
export async function acquireCameraPreview(folder, name, size = 0, mtime = 0) {
  const key = previewKey(folder, name, size, mtime)
  const hit = cache.acquire(key)
  if (hit) return hit
  await enqueue(folder, name, size, mtime, 0)
  const h = cache.acquire(key)
  if (!h) throw new Error('Preview was evicted before use')
  return h
}

/** Warm the cache for a file the viewer may show next (lowest priority). */
export function prefetchCameraPreview(folder, name, size = 0, mtime = 0) {
  if (!cache.has(previewKey(folder, name, size, mtime))) enqueue(folder, name, size, mtime, 1)
}

/** Abandon every request except these `previewKey`s (the current and adjacent files). */
export function keepCameraPreviews(keys) {
  const keep = new Set(keys)
  for (const key of [...inflight.keys()]) if (!keep.has(key)) abort(key)
}

/** Viewer closed: stop waiting for reads that have not finished. */
export function cancelCameraPreviews() {
  for (const key of [...inflight.keys()]) abort(key)
}
export const clearCameraPreviews = () => cache.clear()

/**
 * Lightbox adapter for a card file: the camera thumbnail as placeholder, then the rendered
 * preview. A file the server cannot render shows its thumbnail and the server's reason.
 */
export async function loadCameraViewerItem(item, { placeholder }) {
  if (item.kind === 'video') return null
  const thumb = acquireCameraThumb(item.folder, item.name)
  thumb.then(placeholder, () => {})
  try {
    return await acquireCameraPreview(item.folder, item.name, item.size ?? 0, item.modified ?? 0)
  } catch (e) {
    if (e?.name === 'AbortError') throw e
    const h = await thumb.catch(() => null)
    if (!h) throw e
    return { url: h.url, release: h.release, note: e.message }
  }
}
