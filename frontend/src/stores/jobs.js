import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

const ACTIVE = ['queued', 'pending', 'running']

export const useJobsStore = defineStore('jobs', () => {
  const byId = ref({})
  const lastError = ref(null)

  const list = computed(() =>
    Object.values(byId.value).sort((a, b) => String(b.created).localeCompare(String(a.created))),
  )
  const active = computed(() => list.value.filter((j) => ACTIVE.includes(j.status)))

  const upsert = (job) => {
    if (job?.id) byId.value = { ...byId.value, [job.id]: job }
  }

  async function fetch(query = {}) {
    return guard(lastError, async () => {
      const jobs = await api.listJobs({ query })
      byId.value = Object.fromEntries(jobs.map((j) => [j.id, j]))
      return jobs
    })
  }
  const cancel = (id) =>
    guard(lastError, async () => {
      const job = await api.cancelJob({ path: { job_id: id } })
      upsert(job)
      return job
    })

  const onJobEvent = ({ job }) => upsert(job)

  return { byId, list, active, lastError, fetch, cancel, upsert, onJobEvent }
})
