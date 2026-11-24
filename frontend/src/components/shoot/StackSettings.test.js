import { describe, it, expect, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import StackSettings from './StackSettings.vue'
import { useFocusStore } from '@/stores/focus'
import { useJobsStore } from '@/stores/jobs'
import { useShootStore } from '@/stores/shoot'
import { mountCard, button, inputByLabel } from './testing'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {}, downloadBlob: vi.fn() }))

const range = { min: -100, max: 100, step: 1 }
function setup(opts) {
  return mountCard(StackSettings, {
    ...opts,
    setup: () => {
      useShootStore().mode = 'stack'
      const f = useFocusStore()
      f.status = { relative_position: 0, range }
      f.fetchStatus = vi.fn().mockResolvedValue()
    },
  })
}

describe('StackSettings and the stack shutter', () => {
  it('validates the focus step against the focus range and shows total travel', async () => {
    const { wrapper } = setup()
    const shoot = useShootStore()
    expect(wrapper.find('[data-testid=travel]').text()).toContain('180 steps over 10 frames')
    const input = inputByLabel(wrapper, 'Focus step')
    await input.setValue('500')
    expect(wrapper.find('[data-testid=stack-issue]').text()).toContain('-100 to 100')
    expect(shoot.canPress).toBe(false)
    expect(shoot.blockedReason).toContain('-100 to 100')
    await input.setValue('20')
    expect(wrapper.find('[data-testid=stack-issue]').exists()).toBe(false)
    expect(shoot.canPress).toBe(true)
  })

  it('starts a job, shows progress and the result; Stop cancels, Gallery link navigates', async () => {
    const { wrapper } = setup()
    const shoot = useShootStore()
    const focus = useFocusStore()
    const jobs = useJobsStore()
    focus.stack = vi
      .fn()
      .mockResolvedValue({ id: 'j1', status: 'running', progress: 0.3, message: 'Shot 3/10' })
    jobs.cancel = vi.fn().mockResolvedValue({})
    await shoot.press()
    await flushPromises()
    expect(focus.stack).toHaveBeenCalledWith({
      steps_per_shot: 20,
      shots: 10,
      direction: 'near_to_far',
      settle_ms: 500,
      return_to_start: true,
      name: null,
    })
    expect(wrapper.find('[data-testid=stack-job]').text()).toContain('Shot 3/10')
    expect(shoot.label).toBe('Frame 3 of 10')
    await shoot.press()
    expect(jobs.cancel).toHaveBeenCalledWith('j1')
    jobs.onJobEvent({
      job: {
        id: 'j1',
        status: 'completed',
        progress: 1,
        message: '',
        result: { folder: 'stack_1', file_count: 10 },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('10 files')
    await button(wrapper, 'Open in Gallery').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['gallery', 'stack_1'])
  })

  it('keeps Stop usable under its own lease, but blocks Start under other leases', () => {
    setup({ leasedBy: 'bulb' })
    expect(useShootStore().blockedReason).toBe('Busy: Bulb exposure.')
    expect(useShootStore().canPress).toBe(false)
    setup({ leasedBy: 'focus-stack' })
    expect(useShootStore().blockedReason).toBe('')
  })
})
