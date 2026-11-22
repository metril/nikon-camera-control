import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useRecordingStore = defineStore('recording', () => {
  const status = ref(null)
  const lastClip = ref(null)
  const lastError = ref(null)
  const active = computed(() => !!status.value?.active)
  const set = (s) => (status.value = s)

  const fetchStatus = () => guard(lastError, async () => set(await api.getRecording()))
  const start = (body = {}) => guard(lastError, async () => set(await api.startRecording({ body })))
  const stop = () => guard(lastError, async () => set(await api.stopRecording()))

  function onStarted() {
    status.value = { ...(status.value || { elapsed_s: 0, state: 'recording' }), active: true }
  }
  function onStopped(data) {
    lastClip.value = data
    if (status.value)
      status.value = {
        ...status.value,
        active: false,
        ended_reason: data.reason ?? null,
        warning: data.warning ?? null,
      }
  }

  return { status, active, lastClip, lastError, fetchStatus, start, stop, onStarted, onStopped }
})
