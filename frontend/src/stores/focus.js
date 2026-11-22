import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useFocusStore = defineStore('focus', () => {
  const status = ref(null) // FocusStatus {relative_position, range, ...}
  const lastError = ref(null)

  const fetchStatus = () => guard(lastError, async () => (status.value = await api.getFocus()))
  const autofocus = () => guard(lastError, () => api.autofocus())
  async function manual(steps) {
    const r = await guard(lastError, () => api.manualFocus({ body: { steps } }))
    await fetchStatus().catch(() => {})
    return r
  }
  async function reset() {
    const r = await guard(lastError, () => api.resetFocusPosition())
    await fetchStatus().catch(() => {})
    return r
  }
  /** Returns the focus-stack job. body: StackRequest. */
  const stack = (body) => guard(lastError, () => api.startFocusStack({ body }))
  const clear = () => (status.value = null)

  return { status, lastError, fetchStatus, autofocus, manual, reset, stack, clear }
})
