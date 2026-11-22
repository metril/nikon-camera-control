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

  async function remove(path) {
    await guard(lastError, () => api.deleteFile({ path: { path } }))
    items.value = items.value.filter((f) => f.path !== path)
    total.value = Math.max(0, total.value - 1)
  }

  /**
   * Resolve a thumbnail to something usable as <img src>. Without an API key this is a plain
   * URL; with one it is fetched as a blob (headers) and cached as an object URL (LRU, revoked).
   */
  async function thumbnailSrc(path, size) {
    if (!useAuthStore().apiKey) return thumbnailUrl(path, size)
    const key = `${path}|${size ?? ''}`
    const hit = cache.get(key)
    if (hit) return hit
    if (!inflight.has(key)) {
      inflight.set(
        key,
        api
          .getThumbnail({ path: { path }, query: size ? { size } : {}, parseAs: 'blob' })
          .then((blob) => {
            const url = URL.createObjectURL(blob)
            cache.set(key, url)
            return url
          })
          .finally(() => inflight.delete(key)),
      )
    }
    return inflight.get(key)
  }
  const clearThumbnails = () => cache.clear()

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
    lastError,
    load,
    reload,
    remove,
    thumbnailSrc,
    clearThumbnails,
    download,
  }
})
