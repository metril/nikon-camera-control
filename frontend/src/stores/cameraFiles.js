import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, downloadBlob } from '@/api'
import { guard } from './helpers'

export const useCameraFilesStore = defineStore('cameraFiles', () => {
  const folders = ref([])
  const items = ref([])
  const total = ref(0)
  const query = ref({ folder: '/', recursive: false, page: 1, limit: 50 })
  const loading = ref(false)
  const lastError = ref(null)

  async function loadFolders(folder = '/') {
    return guard(lastError, async () => {
      const out = await api.listCameraFolders({ query: { folder } })
      folders.value = out.folders
      return out
    })
  }
  async function loadFiles(params = {}) {
    query.value = { ...query.value, ...params }
    loading.value = true
    try {
      return await guard(lastError, async () => {
        const page = await api.listCameraFiles({ query: { ...query.value } })
        items.value = page.items
        total.value = page.total
        return page
      })
    } finally {
      loading.value = false
    }
  }
  /** Returns the download job (progress arrives via the jobs store). */
  const downloadAll = (body = {}) => guard(lastError, () => api.downloadAllCameraFiles({ body }))
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
