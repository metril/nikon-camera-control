import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import UiPopover from './UiPopover.vue'

let w
afterEach(() => w?.unmount())

const mountPop = (props = {}) =>
  mount(UiPopover, {
    props: { open: true, title: 'Bracket', ...props },
    slots: { default: '<button id="a">A</button><button id="b">B</button>' },
    attachTo: document.body,
  })
const tick = async () => {
  await w.vm.$nextTick()
  await w.vm.$nextTick()
}

describe('UiPopover', () => {
  it('is a labelled modal dialog and focuses inside', async () => {
    w = mountPop()
    await tick()
    const dlg = document.body.querySelector('[role="dialog"]')
    expect(dlg.getAttribute('aria-modal')).toBe('true')
    expect(dlg.getAttribute('aria-labelledby')).toBeTruthy()
    expect(dlg.contains(document.activeElement)).toBe(true)
  })

  it('Esc and the scrim close it', async () => {
    w = mountPop()
    await tick()
    document.body
      .querySelector('[role="dialog"]')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
    document.body
      .querySelector('[data-test="popover-scrim"]')
      .dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    expect(w.emitted('close')).toHaveLength(2)
  })

  it('traps Tab inside', async () => {
    w = mountPop()
    await tick()
    const b = document.body.querySelector('#b')
    b.focus()
    const e = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    b.dispatchEvent(e)
    expect(e.defaultPrevented).toBe(true)
    expect(document.activeElement.getAttribute('aria-label')).toBe('Close')
  })

  it('places below the anchor and flips above when there is no room', () => {
    w = mountPop({ open: false })
    const { place } = w.vm
    const panel = { width: 300, height: 200 }
    const roomy = place({ top: 100, bottom: 140, left: 50 }, panel, 1280, 800, 'bottom')
    expect(roomy).toMatchObject({ side: 'bottom', top: 148, left: 50 })
    const cramped = place({ top: 700, bottom: 740, left: 50 }, panel, 1280, 800, 'bottom')
    expect(cramped.side).toBe('top')
    expect(cramped.top).toBe(700 - 8 - 200)
  })

  it('clamps horizontally into the viewport', () => {
    w = mountPop({ open: false })
    const r = w.vm.place(
      { top: 100, bottom: 140, left: 1200 },
      { width: 300, height: 100 },
      1280,
      800,
      'bottom',
    )
    expect(r.left).toBe(1280 - 300 - 8)
  })
})
