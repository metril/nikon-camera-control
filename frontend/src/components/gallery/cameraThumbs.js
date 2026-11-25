import { api } from '@/api'
import { BlobUrlLru } from '@/stores/thumbnailCache'

// The camera serves previews one at a time over USB: fetch at most two at once.
const MAX_PARALLEL = 2
const cache = new BlobUrlLru(300)
const inflight = new Map()
const waiting = []
let running = 0

function pump() {
  while (running < MAX_PARALLEL && waiting.length) {
    running++
    waiting.shift().run()
  }
}
const limited = (key, fn) =>
  new Promise((resolve, reject) => {
    waiting.push({
      key,
      reject,
      run: () =>
        fn()
          .then(resolve, reject)
          .finally(() => {
            running--
            pump()
          }),
    })
    pump()
  })

/** Drop a fetch that has not started yet (unmounted, paged away, tab hidden); running ones finish. */
export function cancelCameraThumb(folder, name) {
  const key = `${folder}/${name}`
  const i = waiting.findIndex((w) => w.key === key)
  if (i < 0) return
  const [w] = waiting.splice(i, 1)
  w.reject(new Error('Thumbnail request cancelled'))
}

/** `{ url, release }` for the camera's own preview of one card file (blob so the API key is sent). */
export async function acquireCameraThumb(folder, name) {
  const key = `${folder}/${name}`
  const hit = cache.acquire(key)
  if (hit) return hit
  if (!inflight.has(key)) {
    inflight.set(
      key,
      limited(key, () => api.getCameraThumbnail({ query: { folder, name }, parseAs: 'blob' }))
        .then((blob) => {
          if (!cache.has(key)) cache.set(key, URL.createObjectURL(blob))
        })
        .finally(() => inflight.delete(key)),
    )
  }
  await inflight.get(key)
  const h = cache.acquire(key)
  if (!h) throw new Error('Thumbnail was evicted before use')
  return h
}
export const clearCameraThumbs = () => cache.clear()
