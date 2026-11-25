import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import ConfigForm from './ConfigForm.vue'
import { draft, resetDraft } from './useDraft'
import { useTimelapseStore } from '@/stores/timelapse'

const result = (over = {}) => ({
  config: {},
  resolved_steps: [],
  validated: false,
  min_interval_s: 2,
  estimate: {
    total_sets: 100,
    shots_per_set: 1,
    total_shots: 100,
    duration_s: 990,
    disk_bytes: 5_000_000,
  },
  ...over,
})

function setup() {
  const pinia = createTestingPinia({ createSpy: vi.fn })
  const tl = useTimelapseStore()
  tl.setConfig.mockResolvedValue(result())
  tl.previewDraft.mockResolvedValue(result())
  return { tl, w: mount(ConfigForm, { global: { plugins: [pinia] } }) }
}

describe('ConfigForm', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetDraft()
  })
  afterEach(() => vi.useRealTimers())

  it('debounces the preview call, never saves, and shows server numbers', async () => {
    const { tl, w } = setup()
    const input = w.findAll('input')[1] // interval
    for (const v of ['3', '4', '5']) {
      await input.setValue(v)
      vi.advanceTimersByTime(200)
    }
    expect(tl.previewDraft).not.toHaveBeenCalled()
    vi.advanceTimersByTime(700)
    await vi.runAllTimersAsync()
    expect(tl.previewDraft).toHaveBeenCalledTimes(1)
    expect(tl.previewDraft.mock.calls[0][0].interval_s).toBe(5)
    expect(tl.setConfig).not.toHaveBeenCalled()
    await w.vm.$nextTick()
    expect(w.find('[data-test="total-shots"]').text()).toBe('100')
    expect(w.find('[data-test="disk"]').text()).toBe('4.8 MB')
    expect(w.text()).toContain('applied when you press Start') // previewed, applied on Start
    expect(w.findAll('button').some((b) => b.text() === 'Apply configuration')).toBe(false)
  })

  it('shows dashes, not NaN, and sends nothing for an empty field', async () => {
    const { tl, w } = setup()
    await w.findAll('input')[1].setValue('')
    vi.advanceTimersByTime(2000)
    await vi.runAllTimersAsync()
    expect(tl.previewDraft).not.toHaveBeenCalled()
    expect(w.text()).not.toMatch(/NaN|Infinity/)
    expect(w.text()).toContain('Enter an interval above 0')
  })

  it('shows server errors at the field', async () => {
    const { tl, w } = setup()
    tl.previewDraft.mockRejectedValue({
      message: 'bad',
      details: [{ loc: ['body', 'interval_s'], msg: 'below camera minimum' }],
    })
    draft.intervalS = 1
    await w.vm.$nextTick()
    vi.advanceTimersByTime(700)
    await vi.runAllTimersAsync()
    await w.vm.$nextTick()
    expect(w.text()).toContain('below camera minimum')
  })

  it('labels the Stop-after value input for the chosen limit', async () => {
    const { w } = setup()
    const labels = () => w.findAll('label').map((l) => l.text())
    expect(labels()).toContain('Frames')
    draft.limit = 'duration'
    await w.vm.$nextTick()
    expect(labels()).toContain('Duration')
  })
})
