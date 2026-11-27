import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import TimelapseView from './TimelapseView.vue'
import { draft, resetDraft } from '@/components/timelapse/useDraft'
import { resetLayoutMode } from '@/composables/useLayoutMode'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { usePresetsStore } from '@/stores/presets'
import { useSessionsStore } from '@/stores/sessions'
import { useTimelapseStore } from '@/stores/timelapse'

function mountView(layout) {
  window.history.replaceState({}, '', `/?layout=${layout}`)
  resetLayoutMode()
  const pinia = createTestingPinia({ createSpy: vi.fn })
  useCameraStore().connected = true
  useTimelapseStore().fetchStatus.mockResolvedValue()
  useSettingsStore().fetchCommon.mockResolvedValue()
  usePresetsStore().fetch.mockResolvedValue()
  useSessionsStore().fetch.mockResolvedValue()
  return mount(TimelapseView, { global: { plugins: [pinia] } })
}
const tab = (w, name) => w.findAll('[role=tab]').find((t) => t.text() === name)
const hidden = (w, id) => w.get(id).element.style.display === 'none'

describe('TimelapseView layouts', () => {
  beforeEach(() => {
    resetDraft()
    localStorage.clear()
  })

  it('touch: Timing/Bracket and Run/Sessions are tabs, one panel visible per strip', async () => {
    const w = mountView('touch')
    expect(w.findAll('[role=tab]').map((t) => t.text())).toEqual([
      'Timing',
      'Bracket',
      'Run',
      'Sessions',
    ])
    expect(hidden(w, '#tl-schedule-panel-timing')).toBe(false)
    expect(hidden(w, '#tl-schedule-panel-bracket')).toBe(true)
    expect(hidden(w, '#tl-run-panel-run')).toBe(false)
    expect(hidden(w, '#tl-run-panel-sessions')).toBe(true)
    await tab(w, 'Bracket').trigger('click')
    await tab(w, 'Sessions').trigger('click')
    expect(hidden(w, '#tl-schedule-panel-timing')).toBe(true)
    expect(hidden(w, '#tl-schedule-panel-bracket')).toBe(false)
    expect(hidden(w, '#tl-run-panel-run')).toBe(true)
    expect(hidden(w, '#tl-run-panel-sessions')).toBe(false)
  })

  it('touch: draft state survives tab switches', async () => {
    const w = mountView('touch')
    await tab(w, 'Bracket').trigger('click')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Quick')
      .trigger('click')
    expect(draft.bracket.mode).toBe('quick')
    await tab(w, 'Timing').trigger('click')
    draft.name = 'Dusk'
    await tab(w, 'Bracket').trigger('click')
    expect(draft.bracket.mode).toBe('quick')
    await tab(w, 'Timing').trigger('click')
    expect(w.get('#tl-schedule-panel-timing input').element.value).toBe('Dusk')
    // panels stay mounted, so nothing is torn down by switching
    expect(w.find('[data-type=exposure]').exists()).toBe(true)
  })

  it('touch: the arrow keys move between tabs', async () => {
    const w = mountView('touch')
    await tab(w, 'Timing').trigger('keydown', { key: 'ArrowRight' })
    expect(hidden(w, '#tl-schedule-panel-bracket')).toBe(false)
  })

  it('desktop: no tabs, everything visible, with Ends at', () => {
    const w = mountView('desktop')
    expect(w.findAll('[role=tab]')).toHaveLength(0)
    for (const id of [
      '#tl-schedule-panel-timing',
      '#tl-schedule-panel-bracket',
      '#tl-run-panel-run',
      '#tl-run-panel-sessions',
    ])
      expect(hidden(w, id)).toBe(false)
    expect(w.find('[data-test=ends-at]').exists()).toBe(true)
  })
})
