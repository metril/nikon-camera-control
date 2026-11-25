import { defineStore } from 'pinia'
import { ref } from 'vue'

let nextId = 1
export const NO_TARGET_MESSAGE = 'No storage chosen. Choose one in Settings › Storage.'

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
  const warn = (message, ms = 6000) => push('warn', message, ms)
  /**
   * Errors are sticky (dismissed by the user). Pass the thrown error, not its message: an
   * ApiError keeps code, status, requestId and the camera-reported details.
   * `opts.prefix` is prepended as "prefix: message", `opts.suffix` is appended (e.g. " (reverted)").
   */
  function error(e, { prefix = '', suffix = '' } = {}) {
    const wrap = (m) => `${prefix ? `${prefix}: ` : ''}${m}${suffix}`
    if (typeof e === 'string') return push('error', wrap(e), 0)
    const message = wrap(e?.code === 'NO_TARGET' ? NO_TARGET_MESSAGE : e?.message || 'Error')
    return push('error', message, 0, {
      code: e?.code ?? null,
      status: e?.status ?? null,
      requestId: e?.requestId ?? null,
      reported: e?.details?.prohibit ?? e?.details?.camera_message ?? null,
      manual: e?.details?.nikon_manual ?? null,
    })
  }

  return { items, push, success, info, warn, error, dismiss }
})
