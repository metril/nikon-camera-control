import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import RunPanel from './RunPanel.vue'
import { resetDraft } from './useDraft'
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
    expect(labels(setup('idle').w)).toEqual(['Start'])
    expect(labels(setup('running').w)).toEqual(['Pause', 'Stop'])
    expect(labels(setup('paused').w)).toEqual(['Resume', 'Stop'])
    expect(labels(setup('completed').w)).toContain('Start')
  })

  it('disables Start with a reason when disconnected or leased', () => {
    const a = setup('idle', {}, { connected: false })
    expect(a.w.find('[data-test="start-block"]').text()).toBe('Camera not connected')
    expect(a.w.find('button').attributes('disabled')).toBeDefined()
    const b = setup('idle', {}, { leasedBy: 'recording' })
    expect(b.w.find('[data-test="start-block"]').text()).toContain('recording')
  })

  it('shows the server failure budget, not a constant', () => {
    const { w } = setup('running', { failure_budget: 8 })
    expect(w.text()).toContain('0/8')
  })

  it('Stop needs confirmation', async () => {
    const { tl, w } = setup('running')
    const stop = w.findAll('button').find((b) => b.text() === 'Stop')
    await stop.trigger('click')
    expect(tl.stop).not.toHaveBeenCalled()
    await w
      .findAll('button')
      .find((b) => b.text() === 'Confirm?')
      .trigger('click')
    expect(tl.stop).toHaveBeenCalled()
  })

  it('counts down to the next shot and stops ticking on unmount', async () => {
    const { w } = setup('running')
    expect(w.find('[data-test="next"]').text()).toBe('5 s')
    vi.advanceTimersByTime(2000)
    await w.vm.$nextTick()
    expect(w.find('[data-test="next"]').text()).toBe('3 s')
    w.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('shows disconnect and error messages', () => {
    const { w } = setup('paused', { paused_reason: 'camera_disconnected' })
    expect(w.find('[data-test="disconnected"]').text()).toContain('resume automatically')
    const f = setup('failed', { error: 'card full' })
    expect(f.w.find('[data-test="error"]').text()).toBe('card full')
  })

  it('offers a suggested interval for interval_too_short', async () => {
    const { tl, w } = setup('running', { measured_set_duration_s: 7.31 })
    tl.warning = { code: 'interval_too_short', message: 'Interval too short' }
    await w.vm.$nextTick()
    expect(w.find('[data-test="warning"]').text()).toContain('Use 7.4 s')
  })
})
