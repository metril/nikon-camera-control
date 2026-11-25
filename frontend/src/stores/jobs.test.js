import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: { listJobs: vi.fn() } }))
import { api } from '@/api'
import { useJobsStore } from './jobs'

const job = (id, status = 'running') => ({ id, status, created: id })
const deferred = () => {
  let resolve
  const promise = new Promise((r) => (resolve = r))
  return { promise, resolve }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('jobs.fetch', () => {
  it('keeps a job created by an event during the fetch even if the response lacks it', async () => {
    const d = deferred()
    api.listJobs.mockReturnValueOnce(d.promise)
    const jobs = useJobsStore()
    const p = jobs.fetch()
    jobs.onJobEvent({ job: job('new') })
    d.resolve([job('old')])
    await p
    expect(Object.keys(jobs.byId).sort()).toEqual(['new', 'old'])
  })

  it('prefers the newer event over the response snapshot', async () => {
    const d = deferred()
    api.listJobs.mockReturnValueOnce(d.promise)
    const jobs = useJobsStore()
    const p = jobs.fetch()
    jobs.onJobEvent({ job: job('a', 'completed') })
    d.resolve([job('a', 'running')])
    await p
    expect(jobs.byId.a.status).toBe('completed')
  })

  it('a second fetch starting does not forget the first fetch events, and a stale response is ignored', async () => {
    const d1 = deferred()
    const d2 = deferred()
    api.listJobs.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const jobs = useJobsStore()
    const p1 = jobs.fetch()
    jobs.onJobEvent({ job: job('x', 'completed') })
    const p2 = jobs.fetch()
    d2.resolve([job('x', 'completed'), job('y')])
    await p2
    d1.resolve([job('x', 'running')]) // older snapshot arrives last
    await p1
    expect(jobs.byId.x.status).toBe('completed')
    expect(jobs.byId.y).toBeTruthy()
  })
})

describe('jobs.upsert', () => {
  it('never lets an active status replace a finished one for the same id', () => {
    const jobs = useJobsStore()
    jobs.onJobEvent({ job: { ...job('a', 'failed'), error: 'boom' } })
    jobs.upsert(job('a', 'queued'))
    jobs.upsert(job('a', 'running'))
    expect(jobs.byId.a.status).toBe('failed')
    jobs.upsert(job('a', 'completed'))
    expect(jobs.byId.a.status).toBe('completed')
  })
})
