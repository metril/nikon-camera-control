import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import UiNumber from './UiNumber.vue'

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
