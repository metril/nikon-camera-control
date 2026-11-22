import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import BulbCard from './BulbCard.vue'
import { useBulbStore } from '@/stores/bulb'
import { useJobsStore } from '@/stores/jobs'
import { useFilesStore } from '@/stores/files'
import { mountCard, button, inputByLabel } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn() }))
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function setup(opts) {
  return mountCard(BulbCard, {
    ...opts,
    setup: () => {
      const b = useBulbStore()
      b.fetchStatus = vi.fn().mockResolvedValue()
      useFilesStore().thumbnailSrc = vi.fn().mockResolvedValue('blob:thumb')
    },
  })
}
const job = (over) => ({
  id: 'j1',
  kind: 'bulb',
  status: 'running',
  progress: 0,
  message: '',
  ...over,
})

describe('BulbCard', () => {
  it('counts down client-side, re-anchors on server updates, and Stop cancels the job', async () => {
    const { wrapper } = setup()
    const bulb = useBulbStore()
    const jobs = useJobsStore()
    bulb.start = vi.fn().mockResolvedValue(job())
    jobs.cancel = vi.fn().mockResolvedValue({})
    await button(wrapper, 'Start bulb exposure').trigger('click')
    await flushPromises()
    expect(bulb.start).toHaveBeenCalledWith({ seconds: 30, download: true, filename_prefix: null })
    const t = () => wrapper.find('[data-testid=countdown]').text()
    expect(t()).toBe('0:30')
    await vi.advanceTimersByTimeAsync(5000)
    expect(t()).toBe('0:25')
    jobs.onJobEvent({ job: job({ message: '20s remaining' }) })
    await vi.advanceTimersByTimeAsync(2000)
    expect(t()).toBe('0:18')
    await button(wrapper, 'Close shutter now').trigger('click')
    expect(jobs.cancel).toHaveBeenCalledWith('j1')
  })

  it('stops its timer on unmount', async () => {
    const { wrapper } = setup()
    const bulb = useBulbStore()
    bulb.start = vi.fn().mockResolvedValue(job())
    await button(wrapper, 'Start bulb exposure').trigger('click')
    await flushPromises()
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('quick picks set the exposure; empty exposure blocks Start', async () => {
    const { wrapper } = setup()
    await button(wrapper, '10 min').trigger('click')
    expect(button(wrapper, '10 min').attributes('aria-pressed')).toBe('true')
    const input = inputByLabel(wrapper, 'Exposure')
    await input.setValue('')
    expect(button(wrapper, 'Start bulb exposure').attributes('disabled')).toBeDefined()
  })

  it('renders the loud BULB_SHUTTER_OPEN error with instructions', async () => {
    const { wrapper } = setup()
    const bulb = useBulbStore()
    bulb.status = { active: false, job_id: 'j1' }
    useJobsStore().upsert(
      job({
        status: 'failed',
        error: 'COULD NOT CLOSE THE SHUTTER: check the camera.',
        error_code: 'BULB_SHUTTER_OPEN',
      }),
    )
    await flushPromises()
    const alert = wrapper.find('[data-testid=shutter-open]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain('STILL BE OPEN')
    expect(alert.text()).toContain('shutter button')
    expect(alert.text()).toContain('power-cycle')
  })

  it('shows warnings and the result thumbnail', async () => {
    const { wrapper } = setup()
    useBulbStore().status = { active: false, job_id: 'j1' }
    useJobsStore().upsert(
      job({
        status: 'completed',
        progress: 1,
        result: { files: ['bulb/a.jpg'], warnings: ['Mode dial is not M'] },
      }),
    )
    await flushPromises()
    expect(wrapper.find('[data-testid=bulb-warnings]').text()).toContain('Mode dial is not M')
    expect(wrapper.find('[data-testid=bulb-result] img').attributes('src')).toBe('blob:thumb')
  })

  it('disabled states: disconnected and leased by another feature; Stop stays available for bulb', async () => {
    expect(setup({ connected: false }).wrapper.text()).toContain('Camera not connected')
    const other = setup({ leasedBy: 'recording' })
    expect(other.wrapper.find('[data-testid=busy]').text()).toBe('Busy: recording')
    expect(button(other.wrapper, 'Start bulb exposure').attributes('disabled')).toBeDefined()
    const own = setup({ leasedBy: 'bulb' })
    useBulbStore().status = { active: true, job_id: 'j1' }
    useJobsStore().upsert(job())
    await flushPromises()
    expect(own.wrapper.find('[data-testid=busy]').exists()).toBe(false)
    expect(button(own.wrapper, 'Close shutter now').attributes('disabled')).toBeUndefined()
  })
})
