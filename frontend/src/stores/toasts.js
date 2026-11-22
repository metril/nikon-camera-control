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
  function push(kind, message, ms, extra = {}) {
    const id = nextId++
    items.value = [...items.value.slice(-4), { id, kind, message, ...extra }]
    if (ms > 0)
      timers.set(
        id,
        setTimeout(() => dismiss(id), ms),
      )
    return id
  }
  const success = (message, ms = 3000) => push('success', message, ms)
  const info = (message, ms = 4000) => push('info', message, ms)
  /** Errors are sticky (dismissed by the user); an ApiError keeps code, status and requestId. */
  function error(e) {
    if (typeof e === 'string') return push('error', e, 0)
    return push('error', e?.message || 'Error', 0, {
      code: e?.code ?? null,
      status: e?.status ?? null,
      requestId: e?.requestId ?? null,
    })
  }

  return { items, push, success, info, error, dismiss }
})
