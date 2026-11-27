import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, videoUrl } from '@/api'
import { guard } from './helpers'

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
  /** Plain link: the session cookie authenticates it. */
  async function download(sessionId, name) {
    const a = document.createElement('a')
    a.href = videoUrl(sessionId, name)
    a.download = name
    a.click()
  }

  /** Resolve a video to something usable as <video src>: `{ url, release }`. */
  async function acquire(sessionId, name) {
    return { url: videoUrl(sessionId, name), release() {} }
  }

  return { items, total, lastError, fetch, render, remove, download, acquire }
})
