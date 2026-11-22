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
})
