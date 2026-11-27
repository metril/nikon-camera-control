import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { KeepAlive, defineComponent, h, nextTick, ref } from 'vue'
import { isTypingTarget, isTextTarget, oskOpen, useHotkeys } from './useHotkeys'

describe('isTypingTarget', () => {
  it('ignores form controls, buttons and contenteditable', () => {
    for (const html of [
      '<input>',
      '<select></select>',
      '<textarea></textarea>',
      '<button>x</button>',
      '<div contenteditable="true"></div>',
    ]) {
      const host = document.createElement('div')
      host.innerHTML = html
      expect(isTypingTarget(host.firstElementChild)).toBe(true)
    }
  })
  it('does not ignore the body or plain elements', () => {
    expect(isTypingTarget(document.body)).toBe(false)
    expect(isTypingTarget(document.createElement('div'))).toBe(false)
  })
  it('ignores children of a button', () => {
    const b = document.createElement('button')
    b.innerHTML = '<span id="s">x</span>'
    expect(isTypingTarget(b.firstElementChild)).toBe(true)
  })
})

describe('oskOpen', () => {
  it('follows the data-osk-open flag the on-screen keyboard sets', () => {
    expect(oskOpen()).toBe(false)
    document.documentElement.dataset.oskOpen = ''
    expect(oskOpen()).toBe(true)
    delete document.documentElement.dataset.oskOpen
  })
})

describe('isTextTarget', () => {
  it('matches text controls but not buttons', () => {
    const make = (html) => {
      const host = document.createElement('div')
      host.innerHTML = html
      return host.firstElementChild
    }
    for (const html of [
      '<input>',
      '<textarea></textarea>',
      '<select></select>',
      '<div contenteditable></div>',
    ])
      expect(isTextTarget(make(html))).toBe(true)
    expect(isTextTarget(make('<button>x</button>'))).toBe(false)
  })
})

describe('useHotkeys under KeepAlive', () => {
  it('does not fire while the view is hidden, and fires again once shown', async () => {
    const fn = vi.fn()
    const show = ref(true)
    const View = defineComponent({
      setup() {
        useHotkeys({ '/': fn })
        return () => h('div')
      },
    })
    const w = mount(
      defineComponent({
        setup: () => () => h(KeepAlive, null, show.value ? [h(View)] : [h('span')]),
      }),
      { attachTo: document.body },
    )
    const press = () =>
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))
    press()
    expect(fn).toHaveBeenCalledTimes(1)
    show.value = false
    await nextTick()
    press()
    expect(fn).toHaveBeenCalledTimes(1)
    show.value = true
    await nextTick()
    press()
    expect(fn).toHaveBeenCalledTimes(2)
    w.unmount()
  })
})
