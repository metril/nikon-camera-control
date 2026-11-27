import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import UiKeypad from './UiKeypad.vue'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('UiKeypad', () => {
  it('is a modal dialog; a hardware keyboard works on the focused panel without leaking keys', async () => {
    const anchor = document.createElement('input')
    document.body.appendChild(anchor)
    const outside = vi.fn()
    document.addEventListener('keydown', outside)
    const w = mount(UiKeypad, {
      props: { modelValue: 1, min: 0, max: 100, anchor },
      attachTo: document.body,
    })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    const dlg = document.body.querySelector('[role="dialog"]')
    expect(dlg.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(dlg)
    for (const k of ['4', '2', ' ', 'g', 'Enter'])
      dlg.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }))
    expect(w.emitted('confirm').at(-1)).toEqual([42])
    expect(outside).not.toHaveBeenCalled() // Space / G never reach the app hotkeys
    document.removeEventListener('keydown', outside)
    w.unmount()
    expect(document.activeElement).toBe(anchor) // closing refocuses the input
  })

  it('Esc closes', async () => {
    const w = mount(UiKeypad, { props: { modelValue: 1 }, attachTo: document.body })
    await w.vm.$nextTick()
    document.body
      .querySelector('[role="dialog"]')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })
})
