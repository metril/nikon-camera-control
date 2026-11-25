import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import RunPanel from './RunPanel.vue'
import { draft, resetDraft } from './useDraft'
import { useTimelapseStore } from '@/stores/timelapse'
import { useCameraStore } from '@/stores/camera'
import { useFilesStore } from '@/stores/files'

function setup(state, extra = {}, cam = {}) {
  const pinia = createTestingPinia({ createSpy: vi.fn })
  const tl = useTimelapseStore()
  tl.status = {
    state,
    session_id: 's1',
    counters: {
      frames_planned: 10,
      frames_done: 4,
      sets_done: 4,
      failures: 1,
      consecutive_failures: 0,
    },
    timing: { elapsed_s: 30, eta_s: 60, next_shot_at: new Date(Date.now() + 5000).toISOString() },
    ...extra,
  }
  const c = useCameraStore()
  Object.assign(c, { connected: true, leasedBy: null, ...cam })
  useFilesStore().acquireThumbnail.mockResolvedValue({ url: 'blob:x', release() {} })
  return { tl, w: mount(RunPanel, { global: { plugins: [pinia] } }) }
}
const labels = (w) => w.findAll('button').map((b) => b.text())

describe('RunPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetDraft()
  })
  afterEach(() => vi.useRealTimers())

  it('offers the right buttons per state', () => {
    expect(labels(setup('idle').w)).toEqual(['Start time-lapse'])
    expect(labels(setup('running').w)).toEqual(['Pause', 'Stop'])
    expect(labels(setup('paused').w)).toEqual(['Resume', 'Stop'])
    expect(labels(setup('completed').w)).toContain('Start time-lapse')
  })

  it('disables Start with a reason when disconnected or leased', () => {
    const a = setup('idle', {}, { connected: false })
    expect(a.w.find('[data-test="start-block"]').text()).toBe('Camera not connected')
    expect(a.w.find('button').attributes('disabled')).toBeDefined()
    const b = setup('idle', {}, { leasedBy: 'recording' })
    expect(b.w.find('[data-test="start-block"]').text()).toBe('Busy: Recording')
  })

  it('shows the server failure budget, not a constant', () => {
    const { w } = setup('running', {
      failure_budget: 8,
      counters: {
        frames_planned: 10,
        frames_done: 4,
        sets_done: 4,
        failures: 3,
        consecutive_failures: 2,
      },
    })
    expect(w.text()).toContain('2/8 in a row')
  })

  it('Stop needs confirmation', async () => {
    const { tl, w } = setup('running')
    const stop = w.findAll('button').find((b) => b.text() === 'Stop')
    await stop.trigger('click')
    expect(tl.stop).not.toHaveBeenCalled()
    expect(w.text()).toContain('Stop the time-lapse?')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Stop now')
      .trigger('click')
    expect(tl.stop).toHaveBeenCalled()
  })

  it('counts down to the next shot and stops ticking on unmount', async () => {
    const { w } = setup('running')
    expect(w.find('[data-test="next"]').text()).toBe('in 5 s')
    vi.advanceTimersByTime(2000)
    await w.vm.$nextTick()
    expect(w.find('[data-test="next"]').text()).toBe('in 3 s')
    w.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('shows disconnect and error messages', () => {
    const { w } = setup('paused', { paused_reason: 'camera_disconnected' })
    expect(w.find('[data-test="disconnected"]').text()).toContain('resume automatically')
    const f = setup('failed', { error: 'card full' })
    expect(f.w.find('[data-test="error"]').text()).toContain('card full')
  })

  it('offers a suggested interval for interval_too_short', async () => {
    const { tl, w } = setup('running', { measured_set_duration_s: 7.31 })
    tl.warning = { code: 'interval_too_short', message: 'Interval too short' }
    await w.vm.$nextTick()
    expect(w.find('[data-test="warning"]').text()).toContain('Use 7.4 s')
  })

  it('names warnings with the label map, never a raw code', async () => {
    const { tl, w } = setup('running')
    tl.warning = { code: 'restore_failed' }
    await w.vm.$nextTick()
    const t = w.find('[data-test="warning"]').text()
    expect(t).toContain('Could not restore camera settings')
    expect(t).not.toContain('restore_failed')
  })

  it('shows frames and shots separately for bracketed runs', () => {
    const { w } = setup('running', {
      counters: {
        frames_planned: 30,
        frames_done: 12,
        sets_done: 4,
        failures: 0,
        consecutive_failures: 0,
      },
      config: { bracketing: { mode: 'steps', steps: [{}, {}, {}] } },
    })
    expect(w.text()).toContain('4 of 10 frames')
    expect(w.text()).toContain('12')
  })

  it('before the first frame the bar reads "0 of <planned>" from the draft', () => {
    draft.limit = 'frames'
    draft.totalFrames = 120
    const { w } = setup('idle', { counters: {} })
    expect(w.text()).toContain('0 of 120 frames')
  })
})
