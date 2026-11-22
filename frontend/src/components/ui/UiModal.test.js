import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import UiModal from './UiModal.vue'

let w
afterEach(() => w?.unmount())

const mountModal = (props = {}) =>
  mount(UiModal, {
    props: { open: true, title: 'Hello', ...props },
    slots: { default: '<button id="a">A</button><button id="b">B</button>' },
    attachTo: document.body,
  })

describe('UiModal', () => {
  it('renders a labelled dialog and focuses inside', async () => {
    w = mountModal()
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    const dlg = document.body.querySelector('[role="dialog"]')
    expect(dlg.getAttribute('aria-modal')).toBe('true')
    expect(dlg.contains(document.activeElement)).toBe(true)
  })

  it('Esc emits close', async () => {
    w = mountModal()
    document.body
      .querySelector('[role="dialog"]')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('Esc is ignored when not closable', () => {
    w = mountModal({ closable: false })
    document.body
      .querySelector('[role="dialog"]')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toBeUndefined()
  })

  it('traps Tab between first and last focusable', async () => {
    w = mountModal()
    const dlg = document.body.querySelector('[role="dialog"]')
    const last = dlg.querySelector('#b')
    last.focus()
    const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    dlg.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(dlg.querySelector('button'))
    const back = new KeyboardEvent('keydown', {
      key: 'Tab',
      shiftKey: true,
      bubbles: true,
      cancelable: true,
    })
    dlg.dispatchEvent(back)
    expect(document.activeElement).toBe(last)
  })

  it('renders nothing when closed', () => {
    w = mountModal({ open: false })
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
  })
})
