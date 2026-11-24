import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import RecordingCard from './RecordingCard.vue'
import { useRecordingStore } from '@/stores/recording'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { mountCard, button } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn() }))
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function setup(opts, status = null) {
  return mountCard(RecordingCard, {
    ...opts,
    setup: () => {
      const r = useRecordingStore()
      r.status = status
      r.fetchStatus = vi.fn().mockResolvedValue()
    },
  })
}

describe('RecordingCard', () => {
  it('starts with options, shows a live elapsed timer, and cleans up on unmount', async () => {
    const { wrapper } = setup()
    const rec = useRecordingStore()
    rec.start = vi.fn(async () => {
      rec.status = { active: true, elapsed_s: 0, state: 'recording' }
    })
    await button(wrapper, 'Start recording').trigger('click')
    await flushPromises()
    expect(rec.start).toHaveBeenCalledWith({ max_seconds: null, download_after: false })
    expect(wrapper.find('[data-testid=elapsed]').text()).toBe('0:00')
    await vi.advanceTimersByTimeAsync(65000)
    expect(wrapper.find('[data-testid=elapsed]').text()).toBe('1:05')
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('Stop calls the store; warning, ended reason, clip and download progress are shown', async () => {
    const { wrapper } = setup(
      { leasedBy: 'recording' },
      { active: true, elapsed_s: 5, state: 'recording' },
    )
    const rec = useRecordingStore()
    rec.stop = vi.fn().mockResolvedValue()
    await button(wrapper, 'Stop recording').trigger('click')
    expect(rec.stop).toHaveBeenCalled()
    rec.status = {
      active: false,
      elapsed_s: 12,
      state: 'idle',
      ended_reason: 'max_seconds',
      warning: 'Card nearly full',
      last_clip: { folder: '100NCD500', name: 'DSC_0001.MOV', size: 5242880 },
      job_id: 'd1',
    }
    useJobsStore().upsert({ id: 'd1', status: 'running', progress: 0.5, message: 'Downloading' })
    await flushPromises()
    expect(wrapper.find('[data-testid=rec-warning]').text()).toBe('Card nearly full')
    expect(wrapper.find('[data-testid=ended-reason]').text()).toContain('time limit')
    expect(wrapper.find('[data-testid=last-clip]').text()).toContain('DSC_0001.MOV')
    expect(wrapper.find('[data-testid=last-clip]').text()).toContain('5.0 MB')
  })

  it('shows the movie-mode hint when start fails', async () => {
    const { wrapper, pinia } = setup()
    const rec = useRecordingStore()
    rec.start = vi.fn().mockRejectedValue(new Error('Camera is not in movie mode'))
    await button(wrapper, 'Start recording').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid=start-error]').text()).toContain('live view selector')
    expect(useToastsStore(pinia).items.length).toBe(1)
  })

  it('is disabled when disconnected or leased by another feature', () => {
    expect(setup({ connected: false }).wrapper.text()).toContain('Camera not connected')
    const { wrapper } = setup({ leasedBy: 'bulb' })
    expect(wrapper.find('[data-testid=busy]').text()).toBe('Busy: Bulb exposure')
    expect(button(wrapper, 'Start recording').attributes('disabled')).toBeDefined()
  })
})
