import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import FocusStackCard from './FocusStackCard.vue'
import { useFocusStore } from '@/stores/focus'
import { useJobsStore } from '@/stores/jobs'
import { mountCard, button, inputByLabel } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn() }))
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

const range = { min: -100, max: 100, step: 1 }
function setup(opts) {
  return mountCard(FocusStackCard, {
    ...opts,
    setup: () => {
      const f = useFocusStore()
      f.status = { relative_position: 0, range }
      f.fetchStatus = vi.fn().mockResolvedValue()
    },
  })
}

describe('FocusStackCard', () => {
  it('validates steps per shot against the focus range and shows total travel', async () => {
    const { wrapper } = setup()
    expect(wrapper.find('[data-testid=travel]').text()).toContain(
      'Total travel: 180 steps over 10 shots',
    )
    const input = inputByLabel(wrapper, 'Steps per shot')
    await input.setValue('500')
    expect(wrapper.find('[data-testid=stack-issue]').text()).toContain('-100 to 100')
    expect(button(wrapper, 'Start stack').attributes('disabled')).toBeDefined()
    await input.setValue('20')
    expect(wrapper.find('[data-testid=stack-issue]').exists()).toBe(false)
    expect(button(wrapper, 'Start stack').attributes('disabled')).toBeUndefined()
  })

  it('starts a job, shows progress, result and a Gallery link; cancel calls the jobs store', async () => {
    const { wrapper } = setup()
    const focus = useFocusStore()
    const jobs = useJobsStore()
    focus.stack = vi
      .fn()
      .mockResolvedValue({ id: 'j1', status: 'running', progress: 0.3, message: 'Shot 3/10' })
    jobs.cancel = vi.fn().mockResolvedValue({})
    await button(wrapper, 'Start stack').trigger('click')
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
    await button(wrapper, 'Cancel').trigger('click')
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
    await button(wrapper, 'Open stack_1 in Gallery').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['gallery', 'stack_1'])
  })

  it('keeps Cancel usable while its own lease is held, but blocks Start for other leases', () => {
    const own = setup({ leasedBy: 'focus-stack' })
    expect(own.wrapper.find('[data-testid=busy]').exists()).toBe(false)
    const other = setup({ leasedBy: 'bulb' })
    expect(other.wrapper.find('[data-testid=busy]').text()).toBe('Busy: bulb')
    expect(button(other.wrapper, 'Start stack').attributes('disabled')).toBeDefined()
  })

  it('shows an empty state when disconnected', () => {
    expect(setup({ connected: false }).wrapper.text()).toContain('Camera not connected')
  })
})
