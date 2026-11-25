import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import TimelapseView from './TimelapseView.vue'
import GalleryView from './GalleryView.vue'
import { draft, resetDraft } from '@/components/timelapse/useDraft'
import { useCameraStore } from '@/stores/camera'
import { useTimelapseStore } from '@/stores/timelapse'
import { useSettingsStore } from '@/stores/settings'
import { usePresetsStore } from '@/stores/presets'
import { useSessionsStore } from '@/stores/sessions'
import { useStorageStore } from '@/stores/storage'
import { routeQuery } from '@/components/shell/useTabs'

function mountView(view) {
  const pinia = createTestingPinia({ createSpy: vi.fn })
  const camera = useCameraStore()
  camera.connected = true
  const tl = useTimelapseStore()
  tl.fetchStatus.mockResolvedValue(null)
  useSettingsStore().fetchCommon.mockResolvedValue()
  useSettingsStore().fetchAll.mockResolvedValue()
  usePresetsStore().fetch.mockResolvedValue()
  useSessionsStore().fetch.mockResolvedValue()
  camera.connect.mockResolvedValue()
  camera.fetchStorage.mockResolvedValue({})
  return mount(view, { global: { plugins: [pinia] } })
}
const btn = (w, text) => w.findAll('button').find((b) => b.text() === text)

describe('TimelapseView', () => {
  it('switches bracketing between None, Quick, Custom steps and Preset', async () => {
    resetDraft()
    const w = mountView(TimelapseView)
    await flushPromises()
    expect(w.text()).toContain('One shot per frame')
    for (const [label, mode] of [
      ['Quick', 'quick'],
      ['Custom steps', 'steps'],
      ['Preset', 'preset'],
      ['None', 'none'],
    ]) {
      await btn(w, label).trigger('click')
      expect(draft.bracket.mode).toBe(mode)
    }
  })

  it('shows Save as preset only for Quick and Custom steps', async () => {
    resetDraft()
    const w = mountView(TimelapseView)
    await btn(w, 'Quick').trigger('click')
    draft.bracket.quick.iso = ['100', '200']
    await w.vm.$nextTick()
    expect(w.text()).toContain('Save as preset')
    await btn(w, 'Preset').trigger('click')
    expect(w.text()).not.toContain('Save as preset')
  })

  it('has no raw identifiers in its text', async () => {
    resetDraft()
    const w = mountView(TimelapseView)
    await flushPromises()
    expect(w.text()).not.toMatch(/\w_\w/)
  })

  it('warns when the camera is not connected, with a Connect action', async () => {
    resetDraft()
    const w = mountView(TimelapseView)
    useCameraStore().connected = false
    await w.vm.$nextTick()
    expect(w.text()).toContain('Camera not connected')
    expect(btn(w, 'Connect')).toBeTruthy()
  })
})

describe('GalleryView', () => {
  it('offers the three sources', async () => {
    const w = mountView(GalleryView)
    await flushPromises()
    const labels = w.findAll('button').map((b) => b.text())
    expect(labels).toEqual(
      expect.arrayContaining(['On this server', 'On the camera card', 'Time-lapse videos']),
    )
  })

  it('opens on the camera card when no storage is chosen, until the user picks a tab', async () => {
    const w = mountView(GalleryView)
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = null
    await flushPromises()
    const pressed = () => w.find('[aria-label="Gallery source"] [aria-pressed="true"]').text()
    expect(pressed()).toBe('On the camera card')
    await btn(w, 'On this server').trigger('click')
    expect(pressed()).toBe('On this server')
  })

  it('stays on this server when a storage exists, and switches to it for an open= deep link', async () => {
    const w = mountView(GalleryView)
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = 'loc'
    await btn(w, 'On the camera card').trigger('click')
    routeQuery.value = { open: 'a/b.jpg' }
    await flushPromises()
    expect(w.find('button[aria-pressed="true"]').text()).toBe('On this server')
    routeQuery.value = {}
  })
})
