import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import OnScreenKeyboard from './OnScreenKeyboard.vue'
import { oskTarget } from '@/composables/useOnScreenKeyboard'
import { resetLayoutMode } from '@/composables/useLayoutMode'

const Host = defineComponent({
  setup() {
    const val = ref('')
    const sent = ref(0)
    return () =>
      h('div', [
        h('form', { onSubmit: (e) => (e.preventDefault(), sent.value++) }, [
          h('input', {
            id: 'a',
            value: val.value,
            maxlength: 20,
            onInput: (e) => (val.value = e.target.value),
          }),
          h('input', { id: 'pw', type: 'password' }),
          h('input', { id: 'num', type: 'number' }),
          h('input', { id: 'ro', readonly: true }),
          h('input', { id: 'no', 'data-no-osk': '' }),
          h('textarea', { id: 'ta' }),
        ]),
        h('span', { id: 'val' }, val.value),
        h('span', { id: 'sent' }, String(sent.value)),
        h(OnScreenKeyboard),
      ])
  },
})

let w
const el = (id) => document.getElementById(id)
const ticks = async () => {
  await nextTick()
  await nextTick()
}
const focus = async (id) => {
  el(id).focus()
  await ticks()
}
const key = (sel) => w.find(sel)
const tap = async (label) => {
  const k = w.findAll('.ukey').find((b) => b.text() === label)
  await k.trigger('click')
}

async function mountHost(layout = 'touch') {
  history.replaceState(null, '', `/?layout=${layout}`)
  resetLayoutMode()
  w = mount(Host, { attachTo: document.body })
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => {
  w?.unmount()
  history.replaceState(null, '', '/')
  resetLayoutMode()
  vi.useRealTimers()
})

describe('OnScreenKeyboard', () => {
  it('opens on text field focus in touch and sets inputmode=none', async () => {
    await mountHost()
    expect(key('[data-test=osk]').exists()).toBe(false)
    await focus('a')
    expect(key('[data-test=osk]').exists()).toBe(true)
    expect(el('a').getAttribute('inputmode')).toBe('none')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it('never opens on desktop', async () => {
    await mountHost('desktop')
    await focus('a')
    expect(key('[data-test=osk]').exists()).toBe(false)
  })

  it('ignores number, readonly and data-no-osk inputs', async () => {
    await mountHost()
    for (const id of ['num', 'ro', 'no']) {
      await focus(id)
      expect(key('[data-test=osk]').exists()).toBe(false)
    }
  })

  it('types, updates v-model, shift is one-shot, caps lock on double tap', async () => {
    await mountHost()
    await focus('a')
    await tap('q')
    await tap('⇧')
    await tap('W')
    await tap('e')
    expect(el('val').textContent).toBe('qWe')
    await key('[data-test=osk-shift]').trigger('click')
    await key('[data-test=osk-shift]').trigger('click')
    await tap('R')
    await tap('T')
    expect(el('val').textContent).toBe('qWeRT')
  })

  it('symbols page, space and respects maxlength', async () => {
    await mountHost()
    await focus('a')
    await key('[data-test=osk-page]').trigger('click')
    await tap('@')
    await key('[data-test=osk-space]').trigger('click')
    await key('[data-test=osk-page]').trigger('click')
    await tap('a')
    expect(el('val').textContent).toBe('@ a')
    el('a').value = 'x'.repeat(20)
    await tap('b')
    expect(el('a').value).toBe('x'.repeat(20))
  })

  it('backspace deletes, inserts at the caret, and auto-repeats on hold', async () => {
    vi.useFakeTimers()
    await mountHost()
    await focus('ta')
    for (const c of ['a', 'b', 'c', 'd', 'e']) await tap(c)
    el('ta').setSelectionRange(2, 2)
    await tap('x')
    expect(el('ta').value).toBe('abxcde')
    const back = key('[data-test=osk-back]')
    await back.trigger('pointerdown')
    expect(el('ta').value).toBe('abcde')
    vi.advanceTimersByTime(400 + 60 * 3)
    expect(el('ta').value).toBe('cde')
    await back.trigger('pointerup')
    vi.advanceTimersByTime(500)
    expect(el('ta').value).toBe('cde')
  })

  it('Enter fires keydown, submits the form and closes', async () => {
    await mountHost()
    await focus('a')
    const seen = vi.fn()
    el('a').addEventListener('keydown', (e) => seen(e.key))
    await key('[data-test=osk-enter]').trigger('click')
    expect(seen).toHaveBeenCalledWith('Enter')
    await nextTick()
    expect(el('sent').textContent).toBe('1')
    expect(key('[data-test=osk]').exists()).toBe(false)
    expect(document.activeElement).not.toBe(el('a'))
  })

  it('Enter in a textarea adds a newline and stays open', async () => {
    await mountHost()
    await focus('ta')
    await tap('a')
    await key('[data-test=osk-enter]').trigger('click')
    expect(el('ta').value).toBe('a\n')
    expect(key('[data-test=osk]').exists()).toBe(true)
  })

  it('password: field stays masked, keys type normally', async () => {
    await mountHost()
    await focus('pw')
    await tap('s')
    expect(el('pw').value).toBe('s')
    expect(el('pw').type).toBe('password')
    expect(key('[data-test=osk]').exists()).toBe(true)
  })

  it('closes on hide key, blur, outside tap and route change', async () => {
    await mountHost()
    await focus('a')
    await key('[data-test=osk-hide]').trigger('click')
    expect(key('[data-test=osk]').exists()).toBe(false)
    await focus('a')
    el('a').blur()
    await nextTick()
    expect(oskTarget.value).toBe(null)
    await focus('a')
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await ticks()
    expect(key('[data-test=osk]').exists()).toBe(false)
    await focus('ta')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await ticks()
    expect(key('[data-test=osk]').exists()).toBe(false)
  })
})
