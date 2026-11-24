import { describe, it, expect, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import BracketSettings from './BracketSettings.vue'
import { useCaptureStore } from '@/stores/capture'
import { useJobsStore } from '@/stores/jobs'
import { useShootStore } from '@/stores/shoot'
import { useToastsStore } from '@/stores/toasts'
import { mountCard, button } from './testing'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {}, downloadBlob: vi.fn() }))

function setup(opts) {
  return mountCard(BracketSettings, {
    ...opts,
    setup: () => {
      useShootStore().mode = 'bracket'
    },
  })
}

describe('BracketSettings and the bracket shutter', () => {
  it('sends a quick bracketing with the EV series for the chosen frames and step', async () => {
    const { wrapper } = setup()
    const shoot = useShootStore()
    const capture = useCaptureStore()
    capture.bracket = vi
      .fn()
      .mockResolvedValue({ id: 'j1', status: 'running', progress: 0, message: 'Frame 1 of 5' })
    await button(wrapper, '5').trigger('click')
    await button(wrapper, '⅔ EV').trigger('click')
    expect(wrapper.findAll('[data-testid=ev-mark]')).toHaveLength(5)
    expect(wrapper.find('[data-testid=ev-scale]').attributes('aria-label')).toBe(
      'Bracket frames: −1.3, −0.7, 0, +0.7, +1.3 EV',
    )
    expect(shoot.label).toBe('Capture 5 frames')
    await shoot.press()
    await flushPromises()
    expect(capture.bracket).toHaveBeenCalledWith({
      bracketing: {
        mode: 'quick',
        exposure: ['-1.333', '-0.667', '0', '0.667', '1.333'],
        combine_mode: 'sequence',
      },
      download: true,
      filename_prefix: null,
    })
    expect(wrapper.find('[data-testid=bracket-job]').text()).toContain('Frame 1 of 5')
    expect(shoot.stoppable).toBe(true)
  })

  it('shows the result with a Gallery link, and Stop cancels the job', async () => {
    const { wrapper } = setup()
    const shoot = useShootStore()
    const jobs = useJobsStore()
    useCaptureStore().bracket = vi
      .fn()
      .mockResolvedValue({ id: 'j2', status: 'running', progress: 0, message: '' })
    jobs.cancel = vi.fn().mockResolvedValue({})
    await shoot.press()
    await flushPromises()
    expect(shoot.label).toBe('Stop bracket')
    await shoot.press()
    expect(jobs.cancel).toHaveBeenCalledWith('j2')
    jobs.onJobEvent({
      job: {
        id: 'j2',
        status: 'completed',
        progress: 1,
        message: '',
        result: { directory: 'bracket_1', shots: [{ index: 0 }, { index: 1 }, { index: 2 }] },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Done · 3 frames')
    await button(wrapper, 'Open in Gallery').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['gallery', 'bracket_1'])
  })

  it('surfaces a start failure as a toast', async () => {
    const { pinia } = setup()
    useCaptureStore().bracket = vi.fn().mockRejectedValue(new Error('Camera busy'))
    await useShootStore().press()
    await flushPromises()
    expect(useToastsStore(pinia).items[0].message).toBe('Camera busy')
  })

  it('gives a visible reason when it cannot fire', () => {
    setup({ connected: false })
    expect(useShootStore().blockedReason).toContain('Connect the camera')
    setup({ leasedBy: 'timelapse' })
    expect(useShootStore().blockedReason).toBe('Busy: Time-lapse.')
    expect(useShootStore().canPress).toBe(false)
  })
})
