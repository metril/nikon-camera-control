import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import UiConfirmButton from './UiConfirmButton.vue'

afterEach(() => vi.useRealTimers())

describe('UiConfirmButton', () => {
  it('needs two clicks to emit confirm', async () => {
    const w = mount(UiConfirmButton, { slots: { default: 'Delete' } })
    await w.find('button').trigger('click')
    expect(w.emitted('confirm')).toBeUndefined()
    expect(w.text()).toBe('Confirm?')
    await w.find('button').trigger('click')
    expect(w.emitted('confirm')).toHaveLength(1)
    expect(w.text()).toBe('Delete')
  })

  it('disarms after 3 s', async () => {
    vi.useFakeTimers()
    const w = mount(UiConfirmButton, { props: { confirmText: 'Sure?' }, slots: { default: 'Go' } })
    await w.find('button').trigger('click')
    expect(w.text()).toBe('Sure?')
    vi.advanceTimersByTime(3100)
    await w.vm.$nextTick()
    expect(w.text()).toBe('Go')
    await w.find('button').trigger('click')
    expect(w.emitted('confirm')).toBeUndefined()
  })

  it('does not arm while disabled', async () => {
    const w = mount(UiConfirmButton, { props: { disabled: true }, slots: { default: 'Go' } })
    await w.find('button').trigger('click')
    expect(w.text()).toBe('Go')
  })
})
