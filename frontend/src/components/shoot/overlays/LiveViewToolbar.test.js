import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import LiveViewToolbar from './LiveViewToolbar.vue'
import { useLiveViewStore } from '@/stores/liveview'

const setup = (props) => {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  return mount(LiveViewToolbar, { props, global: { plugins: [pinia] }, attachTo: document.body })
}

describe('LiveViewToolbar', () => {
  it('shows every tool inline by default', () => {
    const w = setup()
    expect(w.findAll('[data-testid^="lv-tool-"]')).toHaveLength(6)
    expect(w.find('[data-testid="lv-more"]').exists()).toBe(false)
    w.unmount()
  })

  it('compact: two tools inline and the rest in a More popover', async () => {
    const w = setup({ compact: true })
    expect(w.findAll('[data-testid^="lv-tool-"]')).toHaveLength(2)
    const more = w.find('[data-testid="lv-more"]')
    expect(more.attributes('aria-expanded')).toBe('false')
    await more.trigger('click')
    expect(more.attributes('aria-expanded')).toBe('true')
    expect(w.findAll('[data-testid^="lv-tool-"]')).toHaveLength(6)
    await w.find('[data-testid="lv-tool-peak"]').trigger('click')
    expect(useLiveViewStore().tools.peak).toBe(true)
    w.unmount()
  })

  it('compact: the More button shows when a hidden tool is on, and Escape closes the popover', async () => {
    const w = setup({ compact: true })
    useLiveViewStore().tools.loupe = true
    await w.vm.$nextTick()
    expect(w.find('[data-testid="lv-more"]').classes()).toContain('on')
    await w.find('[data-testid="lv-more"]').trigger('click')
    await w.find('[data-testid="lv-toolbar"]').trigger('keydown', { key: 'Escape' })
    expect(w.find('[data-testid="lv-more"]').attributes('aria-expanded')).toBe('false')
    w.unmount()
  })
})
