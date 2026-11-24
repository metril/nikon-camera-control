import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import FocusCard from './FocusCard.vue'
import { useFocusStore } from '@/stores/focus'
import { mountCard, deferred } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn() }))

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
})
afterEach(() => vi.useRealTimers())

function setup(opts) {
  return mountCard(FocusCard, {
    ...opts,
    setup: () => {
      const f = useFocusStore()
      f.status = { relative_position: 3, range: { min: -100, max: 100, step: 1 } }
      f.fetchStatus = vi.fn().mockResolvedValue()
    },
  })
}

describe('FocusCard', () => {
  it('hold-to-repeat never has two requests in flight', async () => {
    const { wrapper } = setup()
    const focus = useFocusStore()
    let inflight = 0
    let max = 0
    const pending = []
    focus.manual = vi.fn(() => {
      inflight++
      max = Math.max(max, inflight)
      const d = deferred()
      pending.push(d)
      return d.promise.finally(() => inflight--)
    })
    const far = wrapper.find('button[aria-label="Far"]')
    await far.trigger('pointerdown')
    expect(focus.manual).toHaveBeenCalledWith(50)
    // a long time passes with the first request still pending: no pile-up
    await vi.advanceTimersByTimeAsync(5000)
    expect(focus.manual).toHaveBeenCalledTimes(1)
    pending[0].resolve({})
    await vi.advanceTimersByTimeAsync(400)
    expect(focus.manual).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2000)
    expect(focus.manual).toHaveBeenCalledTimes(2)
    pending[1].resolve({})
    await vi.advanceTimersByTimeAsync(130)
    expect(focus.manual).toHaveBeenCalledTimes(3)
    await far.trigger('pointerup')
    pending[2].resolve({})
    await vi.advanceTimersByTimeAsync(2000)
    expect(focus.manual).toHaveBeenCalledTimes(3)
    expect(max).toBe(1)
  })

  it('stops repeating on unmount and on error', async () => {
    const { wrapper } = setup()
    const focus = useFocusStore()
    focus.manual = vi.fn().mockResolvedValue({})
    await wrapper.find('button[aria-label="Near"]').trigger('pointerdown')
    expect(focus.manual).toHaveBeenLastCalledWith(-50)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(3000)
    expect(focus.manual).toHaveBeenCalledTimes(1)
  })

  it('keyboard activation sends a single step; step sizes persist', async () => {
    const { wrapper } = setup()
    const focus = useFocusStore()
    focus.manual = vi.fn().mockResolvedValue({})
    await wrapper.find('button[aria-label="Far, large step"]').trigger('click')
    expect(focus.manual).toHaveBeenCalledWith(200)
  })

  it('autofocus shows the result and reset zeroes the position', async () => {
    const { wrapper } = setup()
    const focus = useFocusStore()
    focus.autofocus = vi.fn().mockResolvedValue({ ok: true, focused: true })
    focus.reset = vi.fn().mockResolvedValue({})
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Autofocus')
      .trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid=af-result]').text()).toContain('Focused')
    await wrapper
      .findAll('button')
      .find((b) => b.text() === 'Set zero')
      .trigger('click')
    expect(focus.reset).toHaveBeenCalled()
    expect(wrapper.find('[data-testid=focus-pos]').text()).toBe('3')
  })

  it('shows an empty state when disconnected', () => {
    const { wrapper } = setup({ connected: false })
    expect(wrapper.text()).toContain('Camera not connected')
    expect(wrapper.find('button[aria-label="Far"]').exists()).toBe(false)
  })

  it('is disabled with a reason while another feature holds the camera', () => {
    const { wrapper } = setup({ leasedBy: 'timelapse' })
    expect(wrapper.find('[data-testid=busy]').text()).toBe('Busy: time-lapse')
    expect(wrapper.find('button[aria-label="Far"]').attributes('disabled')).toBeDefined()
  })
})
