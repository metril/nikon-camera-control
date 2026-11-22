import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useSessionsStore = defineStore('sessions', () => {
  const items = ref([])
  const total = ref(0)
  const detail = ref(null)
  const frames = ref({ items: [], total: 0 })
  const lastError = ref(null)

  async function fetch(query = {}) {
    return guard(lastError, async () => {
      const page = await api.listSessions({ query })
      items.value = page.items
      total.value = page.total
      return page
    })
  }
  const fetchOne = (id) =>
    guard(
      lastError,
      async () => (detail.value = await api.getSession({ path: { session_id: id } })),
    )
  const fetchFrames = (id, query = {}) =>
    guard(
      lastError,
      async () => (frames.value = await api.listSessionFrames({ path: { session_id: id }, query })),
    )
  async function rename(id, name) {
    const s = await guard(lastError, () =>
      api.renameSession({ path: { session_id: id }, body: { name } }),
    )
    items.value = items.value.map((i) => (i.id === id ? { ...i, name: s.name ?? name } : i))
    return s
  }
  async function remove(id) {
    await guard(lastError, () => api.deleteSession({ path: { session_id: id } }))
    items.value = items.value.filter((i) => i.id !== id)
    total.value = Math.max(0, total.value - 1)
  }

  return { items, total, detail, frames, lastError, fetch, fetchOne, fetchFrames, rename, remove }
})
