import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import UiSegmented from './UiSegmented.vue'

const options = [
  { value: 'a', label: 'A' },
  { value: 'b', label: 'B' },
]

describe('UiSegmented', () => {
  it('single mode sets aria-pressed and emits the value', async () => {
    const w = mount(UiSegmented, { props: { modelValue: 'a', options } })
    const [a, b] = w.findAll('button')
    expect(a.attributes('aria-pressed')).toBe('true')
    expect(b.attributes('aria-pressed')).toBe('false')
    await b.trigger('click')
    expect(w.emitted('update:modelValue')[0]).toEqual(['b'])
  })

  it('multiple mode toggles values in an array', async () => {
    const w = mount(UiSegmented, { props: { modelValue: ['a'], options, multiple: true } })
    const [a, b] = w.findAll('button')
    await b.trigger('click')
    expect(w.emitted('update:modelValue')[0]).toEqual([['a', 'b']])
    await a.trigger('click')
    expect(w.emitted('update:modelValue')[1]).toEqual([[]])
  })

  it('disabled blocks clicks', async () => {
    const w = mount(UiSegmented, { props: { modelValue: 'a', options, disabled: true } })
    await w.findAll('button')[1].trigger('click')
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })

  it('marks the selected segment with an accent underline', () => {
    const w = mount(UiSegmented, { props: { modelValue: 'a', options } })
    const [a, b] = w.findAll('button')
    expect(a.classes().join(' ')).toContain('camera-accent')
    expect(b.classes().join(' ')).not.toContain('camera-accent')
  })
})
