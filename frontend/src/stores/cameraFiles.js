import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, downloadBlob } from '@/api'
import { guard } from './helpers'
import { clearCameraThumbs } from '@/components/gallery/cameraThumbs'

export const useCameraFilesStore = defineStore('cameraFiles', () => {
  const folders = ref([])
  const items = ref([])
  const total = ref(0)
  const query = ref({ folder: '/', recursive: false, page: 1, limit: 50 })
  const loading = ref(false)
  const lastError = ref(null)

  let foldersSeq = 0
  let filesSeq = 0
  async function loadFolders(folder = '/') {
    const seq = ++foldersSeq
    return guard(lastError, async () => {
      const out = await api.listCameraFolders({ query: { folder } })
      if (seq === foldersSeq) folders.value = out.folders
      return out
    })
  }
  async function loadFiles(params = {}) {
    query.value = { ...query.value, ...params }
    loading.value = true
    const seq = ++filesSeq
    try {
      return await guard(lastError, async () => {
        const page = await api.listCameraFiles({ query: { ...query.value } })
        if (seq !== filesSeq) return page // a newer load superseded this one
        items.value = page.items
        total.value = page.total
        return page
      })
    } finally {
      if (seq === filesSeq) loading.value = false
    }
  }
  /** Returns the download job (progress arrives via the jobs store). */
  const downloadAll = (body = {}) =>
    guard(lastError, async () => {
      const job = await api.downloadAllCameraFiles({ body })
      if (body.delete_after) clearCameraThumbs() // card swaps reuse DSC names
      return job
    })
  /** Save one card file locally (blob fetch so the API key header is sent). */
  async function download(folder, name) {
    const blob = await guard(lastError, () =>
      api.downloadCameraFile({ path: { folder, name }, parseAs: 'blob' }),
    )
    downloadBlob(blob, name)
  }
  async function remove(folder, name) {
    await guard(lastError, () => api.deleteCameraFile({ path: { folder, name } }))
    items.value = items.value.filter((f) => !(f.folder === folder && f.name === name))
    clearCameraThumbs()
  }

  return {
    folders,
    items,
    total,
    query,
    loading,
    lastError,
    loadFolders,
    loadFiles,
    downloadAll,
    download,
    remove,
  }
})
