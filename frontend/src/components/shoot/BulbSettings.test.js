import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import BulbSettings from './BulbSettings.vue'
import { useBulbStore } from '@/stores/bulb'
import { useJobsStore } from '@/stores/jobs'
import { useFilesStore } from '@/stores/files'
import { useShootStore } from '@/stores/shoot'
import { mountCard, button, inputByLabel } from './testing'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {}, downloadBlob: vi.fn() }))
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function setup(opts) {
  return mountCard(BulbSettings, {
    ...opts,
    setup: () => {
      useShootStore().mode = 'bulb'
      const b = useBulbStore()
      b.fetchStatus = vi.fn().mockResolvedValue()
      useFilesStore().acquireThumbnail = vi
        .fn()
        .mockResolvedValue({ url: 'blob:thumb', release() {} })
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
function startsJob() {
  const bulb = useBulbStore()
  bulb.start = vi.fn(async () => {
    bulb.jobId = 'j1'
    useJobsStore().upsert(job())
    return job()
  })
  return bulb
}

describe('BulbSettings and the bulb shutter', () => {
  it('counts down client-side, re-anchors on server updates, and the shutter closes it', async () => {
    const { wrapper } = setup()
    const shoot = useShootStore()
    const jobs = useJobsStore()
    const bulb = startsJob()
    jobs.cancel = vi.fn().mockResolvedValue({})
    expect(shoot.label).toBe('Open shutter')
    await shoot.press()
    await flushPromises()
    expect(bulb.start).toHaveBeenCalledWith({ seconds: 30, download: true, filename_prefix: null })
    expect(shoot.label).toBe('Close shutter')
    expect(shoot.stoppable).toBe(true)
    const t = () => wrapper.find('[data-testid=countdown]').text()
    expect(t()).toBe('0:30')
    await vi.advanceTimersByTimeAsync(5000)
    expect(t()).toBe('0:25')
    jobs.onJobEvent({ job: job({ message: '20s remaining' }) })
    await vi.advanceTimersByTimeAsync(2000)
    expect(t()).toBe('0:18')
    await shoot.press()
    expect(jobs.cancel).toHaveBeenCalledWith('j1')
  })

  it('stops its timer on unmount', async () => {
    const { wrapper } = setup()
    startsJob()
    await useShootStore().press()
    await flushPromises()
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('quick times set the exposure; an empty exposure blocks the shutter with a reason', async () => {
    const { wrapper } = setup()
    const shoot = useShootStore()
    await button(wrapper, '2 min').trigger('click')
    expect(button(wrapper, '2 min').attributes('aria-pressed')).toBe('true')
    expect(shoot.bulbForm.seconds).toBe(120)
    await inputByLabel(wrapper, 'Exposure time').setValue('')
    expect(shoot.canPress).toBe(false)
    expect(shoot.blockedReason).toContain('1 to 3600')
  })

  it('renders the shutter-open error with instructions', async () => {
    const { wrapper } = setup()
    useBulbStore().status = { active: false, job_id: 'j1' }
    useJobsStore().upsert(
      job({
        status: 'failed',
        error: 'Could not close the shutter: check the camera.',
        error_code: 'BULB_SHUTTER_OPEN',
      }),
    )
    await flushPromises()
    const alert = wrapper.find('[data-testid=shutter-open]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain('The shutter may still be open')
    expect(alert.text()).toContain('shutter button')
    expect(alert.text()).toContain('off and on')
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

  it('is blocked by another feature, but its own lease can still be stopped', async () => {
    setup({ leasedBy: 'recording' })
    const shoot = useShootStore()
    expect(shoot.blockedReason).toBe('Busy: Recording.')
    expect(shoot.canPress).toBe(false)
    setup({ leasedBy: 'bulb' })
    useBulbStore().status = { active: true, job_id: 'j1' }
    useJobsStore().upsert(job())
    await flushPromises()
    expect(useShootStore().stoppable).toBe(true)
    expect(useShootStore().canPress).toBe(true)
  })
})
