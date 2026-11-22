import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, downloadBlob, videoUrl } from '@/api'
import { guard } from './helpers'
import { useAuthStore } from './auth'

export const useVideosStore = defineStore('videos', () => {
  const items = ref([])
  const total = ref(0)
  const lastError = ref(null)

  async function fetch(query = {}) {
    return guard(lastError, async () => {
      const page = await api.listVideos({ query })
      items.value = page.items
      total.value = page.total
      return page
    })
  }
  /** Start rendering; returns the job. body: RenderRequest. */
  const render = (sessionId, body = {}) =>
    guard(lastError, () => api.renderSessionVideo({ path: { session_id: sessionId }, body }))
  async function remove(sessionId, name) {
    await guard(lastError, () => api.deleteVideo({ path: { session_id: sessionId, name } }))
    items.value = items.value.filter((v) => !(v.session_id === sessionId && v.name === name))
  }
  async function download(sessionId, name) {
    if (!useAuthStore().apiKey) {
      const a = document.createElement('a')
      a.href = videoUrl(sessionId, name)
      a.download = name
      a.click()
      return
    }
    const blob = await guard(lastError, () =>
      api.downloadVideo({ path: { session_id: sessionId, name }, parseAs: 'blob' }),
    )
    downloadBlob(blob, name)
  }

  return { items, total, lastError, fetch, render, remove, download }
})
