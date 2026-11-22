import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useLiveViewStore = defineStore('liveview', () => {
  const status = ref(null)
  const lastError = ref(null)
  const running = computed(() => !!status.value?.running)
  const set = (s) => (status.value = s)

  const fetchStatus = () => guard(lastError, async () => set(await api.getLiveview()))
  const start = () => guard(lastError, async () => set(await api.startLiveview()))
  const stop = () => guard(lastError, async () => set(await api.stopLiveview()))

  const onStarted = () =>
    status.value && (status.value = { ...status.value, running: true, active: true })
  const onStopped = () =>
    status.value && (status.value = { ...status.value, running: false, active: false })
  const reset = () => (status.value = null)

  return { status, running, lastError, fetchStatus, start, stop, onStarted, onStopped, reset }
})
