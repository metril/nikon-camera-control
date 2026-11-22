import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const useBulbStore = defineStore('bulb', () => {
  const status = ref(null)
  const lastError = ref(null)
  const active = computed(() => !!status.value?.active)

  const fetchStatus = () => guard(lastError, async () => (status.value = await api.getBulbStatus()))
  /** Returns the job (cancel it via the jobs store to close the shutter). body: {seconds, download, filename_prefix}. */
  async function start(body) {
    const job = await guard(lastError, () => api.startBulbCapture({ body }))
    fetchStatus().catch(() => {})
    return job
  }
  const onStarted = ({ bulb }) => bulb && fetchStatus().catch(() => {})
  const onComplete = () => (status.value = status.value && { ...status.value, active: false })

  return { status, active, lastError, fetchStatus, start, onStarted, onComplete }
})
