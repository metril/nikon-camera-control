import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { KeepAlive, defineComponent, h, nextTick, ref } from 'vue'
import { useSelection } from './useSelection'

let w
afterEach(() => {
  w?.unmount()
  vi.useRealTimers()
})

function setup(initial = ['a', 'b', 'c', 'd', 'e']) {
  const items = ref(initial)
  let sel
  w = mount(
    defineComponent({
      setup() {
        sel = useSelection({ ids: () => items.value })
        return () => h('div')
      },
    }),
    { attachTo: document.body },
  )
  return { sel, items }
}
const press = (key, init = {}) =>
  document.body.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }),
  )

describe('useSelection', () => {
  it('a plain click does not select until selection mode is on', () => {
    const { sel } = setup()
    expect(sel.click('a', {})).toBe(false)
    expect(sel.selecting.value).toBe(false)
  })

  it('toggles items and leaves selection mode when emptied', () => {
    const { sel } = setup()
    sel.toggle('a')
    sel.toggle('b')
    expect(sel.list.value).toEqual(['a', 'b'])
    expect(sel.selecting.value).toBe(true)
    sel.toggle('a')
    sel.toggle('b')
    expect(sel.selecting.value).toBe(false)
  })

  it('Ctrl-click starts selecting; later plain clicks toggle', () => {
    const { sel } = setup()
    expect(sel.click('b', { ctrlKey: true })).toBe(true)
    expect(sel.click('d', {})).toBe(true)
    expect(sel.list.value).toEqual(['b', 'd'])
  })

  it('Shift-click selects the range from the anchor, in either direction', () => {
    const { sel } = setup()
    sel.click('b', { ctrlKey: true })
    sel.click('d', { shiftKey: true })
    expect(sel.list.value.sort()).toEqual(['b', 'c', 'd'])
    sel.clear()
    sel.start('d')
    sel.click('a', { shiftKey: true })
    expect(sel.list.value.sort()).toEqual(['a', 'b', 'c', 'd'])
  })

  it('Ctrl+A selects all while selecting, and ignores typing targets', () => {
    const { sel } = setup()
    press('a', { ctrlKey: true })
    expect(sel.count.value).toBe(0)
    sel.toggle('a')
    const input = document.createElement('input')
    document.body.append(input)
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', ctrlKey: true, bubbles: true }))
    expect(sel.count.value).toBe(1)
    input.remove()
    press('a', { ctrlKey: true })
    expect(sel.count.value).toBe(5)
    expect(sel.allSelected.value).toBe(true)
  })

  it('Ctrl+A and Esc still work with a button (a tapped tile) focused', () => {
    const { sel } = setup()
    sel.toggle('a')
    const btn = document.createElement('button')
    document.body.append(btn)
    const fire = (init) =>
      btn.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init }))
    fire({ key: 'a', ctrlKey: true })
    expect(sel.count.value).toBe(5)
    fire({ key: 'Escape' })
    expect(sel.selecting.value).toBe(false)
    btn.remove()
  })

  it('ignores keys while its KeepAlive view is hidden', async () => {
    const items = ref(['a', 'b', 'c'])
    const show = ref(true)
    let sel
    const View = defineComponent({
      setup() {
        sel = useSelection({ ids: () => items.value })
        return () => h('div')
      },
    })
    w = mount(
      defineComponent({
        setup: () => () => h(KeepAlive, null, show.value ? [h(View)] : [h('span')]),
      }),
      { attachTo: document.body },
    )
    sel.toggle('a')
    show.value = false
    await nextTick()
    press('a', { ctrlKey: true })
    expect(sel.count.value).toBe(1)
    show.value = true
    await nextTick()
    press('a', { ctrlKey: true })
    expect(sel.count.value).toBe(3)
  })

  it('Esc clears the selection', () => {
    const { sel } = setup()
    sel.selectAll()
    press('Escape')
    expect(sel.selecting.value).toBe(false)
    expect(sel.count.value).toBe(0)
  })

  it('long-press enters selection with the item, and swallows the following click', () => {
    vi.useFakeTimers()
    const { sel } = setup()
    const p = sel.longPress('c')
    p.onPointerdown({ pointerType: 'touch', clientX: 5, clientY: 5 })
    vi.advanceTimersByTime(499)
    expect(sel.selecting.value).toBe(false)
    vi.advanceTimersByTime(2)
    expect(sel.list.value).toEqual(['c'])
    p.onPointerup()
    expect(sel.click('c', {})).toBe(true) // the release click is swallowed
    expect(sel.list.value).toEqual(['c'])
    expect(sel.click('c', {})).toBe(true) // the next tap toggles
    expect(sel.count.value).toBe(0)
  })

  it('moving or releasing early cancels the long-press', () => {
    vi.useFakeTimers()
    const { sel } = setup()
    const p = sel.longPress('a')
    p.onPointerdown({ pointerType: 'touch', clientX: 0, clientY: 0 })
    p.onPointermove({ clientX: 30, clientY: 0 })
    vi.advanceTimersByTime(800)
    expect(sel.selecting.value).toBe(false)
    p.onPointerdown({ pointerType: 'touch', clientX: 0, clientY: 0 })
    vi.advanceTimersByTime(200)
    p.onPointerup()
    vi.advanceTimersByTime(800)
    expect(sel.selecting.value).toBe(false)
  })

  it('start() with no item keeps the mode on until clear()', () => {
    const { sel } = setup()
    sel.start()
    expect(sel.selecting.value).toBe(true)
    sel.clear()
    expect(sel.selecting.value).toBe(false)
  })

  it('drops items that disappear from the list', async () => {
    const { sel, items } = setup()
    sel.selectAll()
    items.value = ['a', 'b']
    await nextTick()
    expect(sel.list.value).toEqual(['a', 'b'])
  })
})
