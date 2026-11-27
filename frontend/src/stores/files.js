import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, thumbnailUrl, fileUrl } from '@/api'
import { guard } from './helpers'

export const useFilesStore = defineStore('files', () => {
  const items = ref([])
  const folders = ref([])
  const total = ref(0)
  const query = ref({ folder: '', page: 1, limit: 50, kind: 'all', sort: 'newest' })
  const loading = ref(false)
  /** Photo (JPEG + RAW) and video totals for the current folder; null until known. */
  const counts = ref({ photos: null, videos: null })
  const lastError = ref(null)

  /** Load a page; `params` are merged into (and remembered as) the current query. */
  let loadSeq = 0
  async function load(params = {}) {
    query.value = { ...query.value, ...params }
    loading.value = true
    const seq = ++loadSeq
    try {
      return await guard(lastError, async () => {
        const page = await api.listFiles({ query: { ...query.value } })
        if (seq !== loadSeq) return page // a newer load superseded this one
        items.value = page.items
        folders.value = page.folders || []
        total.value = page.total
        return page
      })
    } finally {
      if (seq === loadSeq) loading.value = false
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

  /** Delete many files in one request. Returns `{ deleted: [path], failed: [{ path, error }] }`. */
  async function removeMany(paths) {
    const out = await guard(lastError, () => api.deleteFiles({ body: { paths } }))
    const gone = new Set(out.deleted)
    if (gone.size) {
      items.value = items.value.filter((f) => !gone.has(f.path))
      total.value = Math.max(0, total.value - gone.size)
    }
    return out
  }

  /**
   * Download many files: one file goes straight through download(); several become a ZIP whose
   * single-use ticket URL needs no further credentials.
   */
  async function downloadZip(paths) {
    if (paths.length === 1) return download(paths[0])
    const { url } = await guard(lastError, () => api.createZipDownload({ body: { paths } }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'photos.zip'
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  /** Thumbnail as `{ url, release }`; the session cookie authenticates the plain URL. */
  async function acquireThumbnail(path, size) {
    return { url: thumbnailUrl(path, size), release() {} }
  }

  /** Download a file through a plain link (the session cookie authenticates it). */
  async function download(path, name = path.split('/').pop()) {
    const a = document.createElement('a')
    a.href = fileUrl(path)
    a.download = name
    a.click()
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
    removeMany,
    downloadZip,
    acquireThumbnail,
    download,
  }
})
