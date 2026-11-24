import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useFocusStore = defineStore('focus', () => {
  const status = ref(null) // FocusStatus {relative_position, range, ...}
  const lastError = ref(null)

  const fetchStatus = () => guard(lastError, async () => (status.value = await api.getFocus()))
  const autofocus = () => guard(lastError, () => api.autofocus())
  /** Move the camera's AF point; x, y normalized 0..1 of the live view frame. */
  const setPoint = (x, y) => guard(lastError, () => api.setAfPoint({ body: { x, y } }))
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

  return { status, lastError, fetchStatus, autofocus, setPoint, manual, reset, stack, clear }
})
