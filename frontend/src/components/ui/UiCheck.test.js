import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { resetLayoutMode } from '@/composables/useLayoutMode'
import UiCheck from './UiCheck.vue'

const px = (w) => w.find('button').element.style.width

describe('UiCheck', () => {
  beforeEach(() => {
    localStorage.clear()
    resetLayoutMode()
  })

  it('is a round checkbox that toggles through v-model', async () => {
    const w = mount(UiCheck, { props: { modelValue: false, label: 'Select a.jpg' } })
    const b = w.find('button')
    expect(b.attributes('role')).toBe('checkbox')
    expect(b.attributes('aria-checked')).toBe('false')
    expect(b.attributes('aria-label')).toBe('Select a.jpg')
    expect(b.classes()).toContain('rounded-full')
    await b.trigger('click')
    expect(w.emitted('update:modelValue')[0]).toEqual([true])
    await w.setProps({ modelValue: true })
    expect(b.attributes('aria-checked')).toBe('true')
  })

  it('is 28px on touch and 20px on desktop, from the prop or the current layout', () => {
    expect(px(mount(UiCheck, { props: { size: 'touch' } }))).toBe('28px')
    expect(px(mount(UiCheck, { props: { size: 'desktop' } }))).toBe('20px')
    expect(px(mount(UiCheck))).toBe('20px')
    localStorage.setItem('layout', 'touch')
    resetLayoutMode()
    expect(px(mount(UiCheck))).toBe('28px')
  })

  it('does not toggle when disabled', async () => {
    const w = mount(UiCheck, { props: { disabled: true } })
    await w.find('button').trigger('click')
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })
})
