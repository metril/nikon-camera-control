import { defineStore } from 'pinia'
import { ref } from 'vue'

let nextId = 1

export const useToastsStore = defineStore('toasts', () => {
  const items = ref([])
  const timers = new Map()

  function dismiss(id) {
    clearTimeout(timers.get(id))
    timers.delete(id)
    items.value = items.value.filter((t) => t.id !== id)
  }
  function push(kind, message, ms) {
    const id = nextId++
    items.value = [...items.value.slice(-4), { id, kind, message }]
    if (ms > 0)
      timers.set(
        id,
        setTimeout(() => dismiss(id), ms),
      )
    return id
  }
  const success = (message, ms = 3000) => push('success', message, ms)
  const info = (message, ms = 4000) => push('info', message, ms)
  const error = (e, ms = 6000) =>
    push('error', typeof e === 'string' ? e : e?.message || 'Error', ms)

  return { items, push, success, info, error, dismiss }
})
