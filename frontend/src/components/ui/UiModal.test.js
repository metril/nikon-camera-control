import { describe, it, expect, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
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

  it('Esc closes even when focus fell to the page after a state change', async () => {
    w = mountModal()
    await w.vm.$nextTick()
    document.body.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('moves focus back inside when the focused element is removed', async () => {
    w = mount(UiModal, {
      props: { open: true, title: 'Hello' },
      slots: { default: '<button id="a">A</button>' },
      attachTo: document.body,
    })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    const dlg = document.body.querySelector('[role="dialog"]')
    const extra = document.createElement('button')
    dlg.appendChild(extra)
    extra.focus()
    extra.remove()
    await new Promise((r) => setTimeout(r, 0))
    expect(dlg.contains(document.activeElement)).toBe(true)
  })

  it('only the top-most modal reacts to Esc', async () => {
    const outer = mountModal()
    const inner = mount(UiModal, {
      props: { open: true, title: 'Inner' },
      slots: { default: '<button>x</button>' },
      attachTo: document.body,
    })
    await inner.vm.$nextTick()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(inner.emitted('close')).toHaveLength(1)
    expect(outer.emitted('close')).toBeUndefined()
    inner.unmount()
    outer.unmount()
  })

  it('a modal opened and closed within one tick never creates an observer', async () => {
    const created = []
    const disconnects = []
    const Real = globalThis.MutationObserver
    vi.stubGlobal(
      'MutationObserver',
      class {
        constructor(cb) {
          this.inner = new Real(cb)
          created.push(this)
        }
        observe(...a) {
          this.inner.observe(...a)
        }
        disconnect() {
          disconnects.push(this)
          this.inner.disconnect()
        }
      },
    )
    try {
      w = mountModal({ open: false })
      w.setProps({ open: true })
      await Promise.resolve()
      w.setProps({ open: false })
      await flushPromises()
      const leaked = created.filter((o) => !disconnects.includes(o))
      expect(leaked).toHaveLength(0)
      expect(document.body.querySelector('[role="dialog"]')).toBeNull()
    } finally {
      vi.stubGlobal('MutationObserver', Real)
    }
  })
})
