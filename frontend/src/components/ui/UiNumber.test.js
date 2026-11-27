import { describe, it, expect, afterEach, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import UiNumber from './UiNumber.vue'
import { resetLayoutMode } from '@/composables/useLayoutMode'

const emitted = (w) => (w.emitted('update:modelValue') || []).map((e) => e[0])

describe('UiNumber', () => {
  it('emits finite numbers or null only, never NaN', async () => {
    const w = mount(UiNumber, { props: { modelValue: 5, min: 0, max: 10 } })
    const input = w.find('input')
    for (const raw of ['abc', '-', '1e999', 'Infinity', 'NaN']) await input.setValue(raw)
    await input.setValue('7')
    await input.setValue('')
    const out = emitted(w)
    expect(out.every((v) => v === null || Number.isFinite(v))).toBe(true)
    expect(out).toContain(7)
    expect(out).toContain(null)
  })

  it('clamps to min/max on change and accepts comma decimals', async () => {
    const w = mount(UiNumber, { props: { modelValue: 5, min: 0, max: 10, step: 0.5 } })
    const input = w.find('input')
    await input.setValue('99')
    await input.trigger('change')
    expect(emitted(w).at(-1)).toBe(10)
    await input.setValue('2,5')
    expect(emitted(w).at(-1)).toBe(2.5)
  })

  it('arrow keys step within bounds', async () => {
    const w = mount(UiNumber, { props: { modelValue: 9.9, max: 10, step: 0.1 } })
    await w.find('input').trigger('keydown', { key: 'ArrowUp' })
    expect(emitted(w).at(-1)).toBe(10)
  })

  it('shows the unit and label', () => {
    const w = mount(UiNumber, { props: { modelValue: 1, unit: 's', label: 'Delay' } })
    expect(w.text()).toContain('s')
    expect(w.find('label').attributes('for')).toBe(w.find('input').attributes('id'))
  })

  it('commit fires once per finished edit (Enter then blur), never per keystroke', async () => {
    const w = mount(UiNumber, {
      props: { modelValue: 100, min: 100, max: 3200, step: 100, snap: true },
    })
    const input = w.find('input')
    for (const v of ['1', '15', '150', '1500']) {
      input.element.value = v
      await input.trigger('input')
    }
    expect(w.emitted('commit')).toBeUndefined()
    await input.trigger('keydown', { key: 'Enter' })
    await input.trigger('blur')
    await input.trigger('change')
    expect(w.emitted('commit')).toEqual([[1500]])
  })

  it('commit clamps and snaps to step; spinner keys commit immediately', async () => {
    const w = mount(UiNumber, {
      props: { modelValue: 100, min: 100, max: 3200, step: 100, snap: true },
    })
    const input = w.find('input')
    await input.setValue('1540')
    await input.trigger('blur')
    expect(w.emitted('commit').at(-1)).toEqual([1500])
    await input.setValue('99999')
    await input.trigger('blur')
    expect(w.emitted('commit').at(-1)).toEqual([3200])
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(w.emitted('commit').at(-1)).toEqual([3100])
  })
})

describe('UiNumber on touch', () => {
  beforeEach(() => {
    localStorage.setItem('layout', 'touch')
    resetLayoutMode()
  })
  afterEach(() => {
    localStorage.removeItem('layout')
    resetLayoutMode()
    document.body.innerHTML = ''
  })
  const mountTouch = (props) => mount(UiNumber, { props, attachTo: document.body })
  const key = (t) =>
    [...document.body.querySelectorAll('[data-test="keypad"] button')].find(
      (b) => b.textContent.trim() === t,
    )
  const tap = (...keys) => keys.forEach((k) => key(k).click())

  it('has a stepper on each side that steps by step and stops at the bounds', async () => {
    const w = mountTouch({ modelValue: 9, min: 0, max: 10, step: 0.5 })
    expect(w.find('[data-test="num-dec"]').exists()).toBe(true)
    await w.find('[data-test="num-inc"]').trigger('click')
    expect(emitted(w).at(-1)).toBe(9.5)
    await w.setProps({ modelValue: 10 })
    expect(w.find('[data-test="num-inc"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="num-dec"]').attributes('disabled')).toBeUndefined()
    w.unmount()
  })

  it('opens a keypad on tapping the value; OK commits the typed number', async () => {
    const w = mountTouch({ modelValue: 5, min: 0, max: 100, step: 1 })
    expect(w.find('input').attributes('readonly')).toBeDefined()
    await w.find('input').trigger('click')
    expect(document.body.querySelector('[data-test="keypad"]')).not.toBeNull()
    tap('4', '2', 'OK')
    await w.vm.$nextTick()
    expect(emitted(w).at(-1)).toBe(42)
    expect(w.emitted('commit').at(-1)).toEqual([42])
    expect(document.body.querySelector('[data-test="keypad"]')).toBeNull()
    w.unmount()
  })

  it('keypad clamps to min/max, snaps to the step, and offers only keys that fit the range', async () => {
    const w = mountTouch({ modelValue: 5, min: 0, max: 10, step: 1, snap: true })
    await w.find('input').trigger('click')
    // integer step: no decimal point; min 0: no sign
    expect(key('.').disabled).toBe(true)
    expect(key('±').disabled).toBe(true)
    tap('9', '9', 'OK')
    await w.vm.$nextTick()
    expect(emitted(w).at(-1)).toBe(10)
    w.unmount()
    const d = mountTouch({ modelValue: 0, min: -5, max: 5, step: 0.5 })
    await d.find('input').trigger('click')
    expect(key('.').disabled).toBe(false)
    tap('±', '2', '.', '5', '8', 'OK') // a second decimal is ignored (step has one)
    await d.vm.$nextTick()
    expect(emitted(d).at(-1)).toBe(-2.5)
    d.unmount()
  })

  it('backspace edits and an empty OK closes without a change', async () => {
    const w = mountTouch({ modelValue: 5, min: 0, max: 100 })
    await w.find('input').trigger('click')
    tap('1', '2', '⌫', 'OK')
    await w.vm.$nextTick()
    expect(emitted(w).at(-1)).toBe(1)
    await w.setProps({ modelValue: 1 }) // the parent applies the value
    const n = emitted(w).length
    await w.find('input').trigger('click')
    tap('OK')
    await w.vm.$nextTick()
    expect(emitted(w)).toHaveLength(n)
    expect(document.body.querySelector('[data-test="keypad"]')).toBeNull()
    w.unmount()
  })
})

describe('UiNumber keypad decimals', () => {
  beforeEach(() => {
    localStorage.setItem('layout', 'touch')
    resetLayoutMode()
  })
  afterEach(() => {
    localStorage.removeItem('layout')
    resetLayoutMode()
    document.body.innerHTML = ''
  })
  const dotDisabled = () =>
    [...document.body.querySelectorAll('[data-test="keypad"] button')].find(
      (b) => b.textContent.trim() === '.',
    ).disabled

  it('allows decimals when min has them, even with an integer step', async () => {
    const w = mount(UiNumber, {
      props: { modelValue: 1, min: 0.1, step: 1 },
      attachTo: document.body,
    })
    await w.find('input').trigger('click')
    expect(dotDisabled()).toBe(false)
    w.unmount()
  })

  it('an explicit decimals prop wins; 0 disables the point', async () => {
    const a = mount(UiNumber, {
      props: { modelValue: 1, step: 1, decimals: 2 },
      attachTo: document.body,
    })
    await a.find('input').trigger('click')
    expect(dotDisabled()).toBe(false)
    a.unmount()
    const b = mount(UiNumber, {
      props: { modelValue: 1, step: 0.5, decimals: 0 },
      attachTo: document.body,
    })
    await b.find('input').trigger('click')
    expect(dotDisabled()).toBe(true)
    b.unmount()
  })
})

describe('UiNumber on desktop', () => {
  it('has no steppers or keypad', async () => {
    const w = mount(UiNumber, { props: { modelValue: 1 } })
    expect(w.find('[data-test="num-inc"]').exists()).toBe(false)
    await w.find('input').trigger('click')
    expect(document.body.querySelector('[data-test="keypad"]')).toBeNull()
  })
})
