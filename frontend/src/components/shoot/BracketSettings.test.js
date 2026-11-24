import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import BracketCard from './BracketCard.vue'
import { useCaptureStore } from '@/stores/capture'
import { usePresetsStore } from '@/stores/presets'
import { useJobsStore } from '@/stores/jobs'
import { mountCard, button } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn() }))
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

const bracketPreset = { id: 'builtin-exposure_3', kind: 'bracket', name: '3 shots', builtin: true }
function setup(opts) {
  return mountCard(BracketCard, {
    ...opts,
    setup: () => {
      const p = usePresetsStore()
      p.items = [bracketPreset, { id: 's1', kind: 'settings', name: 'Night', values: { iso: 800 } }]
      p.fetch = vi.fn().mockResolvedValue()
    },
  })
}

describe('BracketCard', () => {
  it('sends a quick bracketing with the EV series for the chosen shots and step', async () => {
    const { wrapper } = setup()
    const capture = useCaptureStore()
    capture.bracket = vi
      .fn()
      .mockResolvedValue({ id: 'j1', status: 'running', progress: 0, message: 'Step 1/7' })
    await button(wrapper, '7 shots').trigger('click')
    await button(wrapper, '2 EV step').trigger('click')
    expect(wrapper.find('[data-testid=ev-series]').text()).toBe('EV: -6, -4, -2, 0, +2, +4, +6')
    await button(wrapper, 'Capture bracket').trigger('click')
    await flushPromises()
    expect(capture.bracket).toHaveBeenCalledWith({
      bracketing: {
        mode: 'quick',
        exposure: ['-6', '-4', '-2', '0', '2', '4', '6'],
        combine_mode: 'sequence',
      },
      download: true,
      filename_prefix: null,
    })
    expect(wrapper.find('[data-testid=bracket-job]').text()).toContain('Step 1/7')
  })

  it('preset source sends mode preset, previews resolved steps and groups result files by step', async () => {
    const { wrapper } = setup()
    const presets = usePresetsStore()
    const capture = useCaptureStore()
    const jobs = useJobsStore()
    presets.apply = vi.fn().mockResolvedValue({
      kind: 'bracket',
      steps: [{ index: 0, label: '-2 EV', settings: { exposurecompensation: '-2' } }],
    })
    capture.bracket = vi
      .fn()
      .mockResolvedValue({ id: 'j2', status: 'running', progress: 0, message: '' })
    await button(wrapper, 'Preset').trigger('click')
    expect(wrapper.text()).not.toContain('Night')
    const select = wrapper.find('select')
    await select.setValue('builtin-exposure_3')
    await button(wrapper, 'Show resolved steps').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid=resolved-steps]').text()).toContain('-2 EV')
    await button(wrapper, 'Capture bracket').trigger('click')
    await flushPromises()
    expect(capture.bracket.mock.calls[0][0].bracketing).toEqual({
      mode: 'preset',
      preset: 'builtin-exposure_3',
    })
    jobs.onJobEvent({
      job: {
        id: 'j2',
        status: 'completed',
        progress: 1,
        message: '',
        result: {
          directory: 'bracket_1',
          shots: [{ index: 0, label: '-2 EV', files: ['bracket_1/a.jpg'], camera_files: [] }],
        },
      },
    })
    await flushPromises()
    expect(wrapper.find('[data-testid=bracket-shots]').text()).toContain('-2 EV')
    expect(wrapper.find('[data-testid=bracket-shots]').text()).toContain('bracket_1/a.jpg')
  })

  it('surfaces a start failure (409 busy) as a toast', async () => {
    const { wrapper, pinia } = setup()
    const capture = useCaptureStore()
    capture.bracket = vi.fn().mockRejectedValue(new Error('Camera busy'))
    await button(wrapper, 'Capture bracket').trigger('click')
    await flushPromises()
    const { useToastsStore } = await import('@/stores/toasts')
    expect(useToastsStore(pinia).items[0].message).toBe('Camera busy')
  })

  it('is disabled when disconnected / leased', () => {
    expect(setup({ connected: false }).wrapper.text()).toContain('Camera not connected')
    const { wrapper } = setup({ leasedBy: 'timelapse' })
    expect(wrapper.find('[data-testid=busy]').text()).toBe('Busy: time-lapse')
    expect(button(wrapper, 'Capture bracket').attributes('disabled')).toBeDefined()
  })
})
