import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, thumbnailUrl, fileUrl, downloadBlob } from '@/api'
import { guard } from './helpers'
import { useAuthStore } from './auth'
import { BlobUrlLru } from './thumbnailCache'

export const useFilesStore = defineStore('files', () => {
  const items = ref([])
  const folders = ref([])
  const total = ref(0)
  const query = ref({ folder: '', page: 1, limit: 50, kind: 'all', sort: 'newest' })
  const loading = ref(false)
  /** Photo (JPEG + RAW) and video totals for the current folder; null until known. */
  const counts = ref({ photos: null, videos: null })
  const lastError = ref(null)
  const cache = new BlobUrlLru(200)
  const inflight = new Map()

  /** Load a page; `params` are merged into (and remembered as) the current query. */
  async function load(params = {}) {
    query.value = { ...query.value, ...params }
    loading.value = true
    try {
      return await guard(lastError, async () => {
        const page = await api.listFiles({ query: { ...query.value } })
        items.value = page.items
        folders.value = page.folders || []
        total.value = page.total
        return page
      })
    } finally {
      loading.value = false
    }
  }
  const reload = () => load()

  /** Cosmetic totals for the gallery filter; a failure just leaves the old numbers. */
  async function loadCounts() {
    const folder = query.value.folder
    const total = async (kind) =>
      (await api.listFiles({ query: { folder, page: 1, limit: 1, kind, sort: 'newest' } })).total
    try {
      const [image, raw, video] = await Promise.all([total('image'), total('raw'), total('video')])
      counts.value = { photos: image + raw, videos: video }
    } catch {
      /* the filter works without counts */
    }
  }

  async function remove(path) {
    await guard(lastError, () => api.deleteFile({ path: { path } }))
    items.value = items.value.filter((f) => f.path !== path)
    total.value = Math.max(0, total.value - 1)
  }

  /**
   * Resolve a thumbnail to something usable as <img src>: `{ url, release }`. Without an API
   * key this is a plain URL; with one it is fetched as a blob (headers) and cached as a
   * reference-counted object URL. Call release() when the image is unmounted or its src changes;
   * the URL is revoked only once evicted AND unreferenced.
   */
  async function acquireThumbnail(path, size) {
    if (!useAuthStore().apiKey) return { url: thumbnailUrl(path, size), release() {} }
    const key = `${path}|${size ?? ''}`
    const hit = cache.acquire(key)
    if (hit) return hit
    if (!inflight.has(key)) {
      inflight.set(
        key,
        api
          .getThumbnail({ path: { path }, query: size ? { size } : {}, parseAs: 'blob' })
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

  /** Download a file; uses a blob when an API key is needed, a plain link otherwise. */
  async function download(path, name = path.split('/').pop()) {
    if (!useAuthStore().apiKey) {
      const a = document.createElement('a')
      a.href = fileUrl(path)
      a.download = name
      a.click()
      return
    }
    const blob = await guard(lastError, () => api.downloadFile({ path: { path }, parseAs: 'blob' }))
    downloadBlob(blob, name)
  }

  return {
    items,
    folders,
    total,
    query,
    loading,
    counts,
    lastError,
    load,
    loadCounts,
    reload,
    remove,
    acquireThumbnail,
    download,
  }
})
