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

  let seq = 0
  const inflight = new Map() // fetch seq -> ids upserted (by events) since that fetch started

  const upsert = (job) => {
    if (!job?.id) return
    inflight.forEach((ids) => ids.add(job.id))
    byId.value = { ...byId.value, [job.id]: job }
  }

  async function fetch(query = {}) {
    return guard(lastError, async () => {
      const mine = ++seq
      const touched = new Set()
      inflight.set(mine, touched)
      try {
        const jobs = await api.listJobs({ query })
        if (mine !== seq) return jobs // a newer fetch owns the state
        // an event that arrived during the request is newer than the response snapshot
        const next = Object.fromEntries(
          jobs.map((j) => [j.id, touched.has(j.id) && byId.value[j.id] ? byId.value[j.id] : j]),
        )
        for (const id of touched) if (!(id in next) && byId.value[id]) next[id] = byId.value[id]
        byId.value = next
        return jobs
      } finally {
        inflight.delete(mine)
      }
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
