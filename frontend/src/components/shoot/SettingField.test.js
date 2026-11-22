import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SettingField from './SettingField.vue'

const range = {
  name: 'iso',
  label: 'ISO Speed',
  type: 'range',
  value: 100,
  writable: true,
  readonly: false,
  range: { min: 100, max: 3200, step: 100 },
}

describe('SettingField', () => {
  it('writes a range setting once on commit, not per keystroke, and skips unchanged values', async () => {
    const w = mount(SettingField, { props: { setting: range } })
    const input = w.find('input')
    for (const v of ['1', '15', '150', '1500']) {
      input.element.value = v
      await input.trigger('input')
    }
    expect(w.emitted('change')).toBeUndefined()
    await input.trigger('keydown', { key: 'Enter' })
    await input.trigger('blur')
    expect(w.emitted('change')).toEqual([['iso', 1500]])
    input.element.value = '100'
    await input.trigger('input')
    await input.trigger('blur')
    expect(w.emitted('change')).toHaveLength(1) // equals the current value: no write
  })

  it('renders each label once, associated with its control', () => {
    const w = mount(SettingField, { props: { setting: range } })
    expect(w.text().match(/ISO Speed/g)).toHaveLength(1)
    expect(w.find('label').attributes('for')).toBe(w.find('input').attributes('id'))
  })
})
