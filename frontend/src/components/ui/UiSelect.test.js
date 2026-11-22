import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import UiSelect from './UiSelect.vue'

describe('UiSelect', () => {
  it('accepts strings and returns original typed values', async () => {
    const w = mount(UiSelect, {
      props: {
        modelValue: 1,
        options: [
          { value: 1, label: 'One' },
          { value: 2, label: 'Two' },
        ],
      },
    })
    const sel = w.find('select')
    sel.element.selectedIndex = 1
    await sel.trigger('change')
    expect(w.emitted('update:modelValue')[0]).toEqual([2])
    const s = mount(UiSelect, { props: { modelValue: 'x', options: ['x', 'y'] } })
    expect(s.findAll('option').map((o) => o.text())).toEqual(['x', 'y'])
  })
})
