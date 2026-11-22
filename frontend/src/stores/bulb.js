import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'
import { useJobsStore } from './jobs'

const RUNNING = ['queued', 'pending', 'running']

export const useBulbStore = defineStore('bulb', () => {
  const status = ref(null) // GET /bulb: remaining time and the running job id
  const jobId = ref(null) // the bulb job we follow; its state comes from the jobs store
  const lastError = ref(null)

  const followedId = computed(() => jobId.value || status.value?.job_id || null)
  const job = computed(() =>
    followedId.value ? useJobsStore().byId[followedId.value] || null : null,
  )
  const active = computed(() =>
    job.value ? RUNNING.includes(job.value.status) : !!status.value?.active,
  )

  const fetchStatus = () =>
    guard(lastError, async () => {
      status.value = await api.getBulbStatus()
      if (status.value.active && status.value.job_id) jobId.value = status.value.job_id
      return status.value
    })
  /** Returns the job (cancel it via the jobs store to close the shutter). body: {seconds, download, filename_prefix}. */
  async function start(body) {
    const j = await guard(lastError, () => api.startBulbCapture({ body }))
    useJobsStore().upsert(j)
    jobId.value = j.id
    fetchStatus().catch(() => {})
    return j
  }
  const onStarted = ({ bulb }) => bulb && fetchStatus().catch(() => {})
  const onComplete = () => (status.value = status.value && { ...status.value, active: false })

  return { status, jobId, job, active, lastError, fetchStatus, start, onStarted, onComplete }
})
