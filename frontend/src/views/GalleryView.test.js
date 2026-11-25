import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { h, KeepAlive, ref } from 'vue'
import GalleryView from './GalleryView.vue'
import { useCameraStore } from '@/stores/camera'
import { useStorageStore } from '@/stores/storage'
import { routeQuery } from '@/components/shell/useTabs'

vi.mock('@/components/gallery/LocalFiles.vue', () => ({
  default: { name: 'LocalFiles', template: '<div data-testid="local" />' },
}))
vi.mock('@/components/gallery/CameraFiles.vue', () => ({
  default: { name: 'CameraFiles', template: '<div data-testid="cam" />' },
}))

let wrapper
function setup({ connected = true, target = 'loc', cards } = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const cam = useCameraStore(pinia)
  cam.connected = connected
  cam.storage = cards ? { cards } : null
  vi.spyOn(cam, 'fetchStorage').mockResolvedValue()
  const st = useStorageStore(pinia)
  st.loaded = true
  st.targetId = target
  st.locations = target
    ? [{ id: 'loc', kind: 'usb', name: 'usb1', label: 'Data', mounted: true, free: 2e11 }]
    : []
  wrapper = mount(GalleryView, { global: { plugins: [pinia] }, attachTo: document.body })
  return { cam, st }
}
const radios = () => wrapper.findAll('[role=radio]')

beforeEach(() => {
  localStorage.clear()
  location.hash = '#/gallery'
})
afterEach(() => wrapper?.unmount())

describe('GalleryView sources', () => {
  it('shows camera and storage cards and defaults to storage', async () => {
    setup({ cards: [{ free_kb: 1e6 }, { free_kb: 1e6 }] })
    await flushPromises()
    expect(radios()).toHaveLength(2)
    expect(radios()[0].text()).toContain('2 cards')
    expect(radios()[1].text()).toContain('Data')
    expect(radios()[1].attributes('aria-checked')).toBe('true')
    expect(wrapper.find('[data-testid=local]').exists()).toBe(true)
  })

  it('describes the storage drive as a whole, not the open folder', async () => {
    const { st } = setup()
    st.locations = [{ ...st.locations[0], size: 1e12 }]
    await flushPromises()
    expect(radios()[1].text()).toMatch(/GB free of [\d.]+ GB/)
    expect(radios()[1].text()).not.toMatch(/\bfiles?\b/)
  })

  it('shows Not connected and a Choose link without storage, opening on the camera', async () => {
    setup({ connected: false, target: null })
    await flushPromises()
    expect(radios()[0].text()).toContain('Not connected')
    expect(radios()[1].text()).toContain('Storage')
    expect(radios()[1].text()).toContain('No storage chosen')
    expect(wrapper.find('a').attributes('href')).toBe('#/settings?section=storage')
  })

  it('defaults to the camera when no storage is chosen and the camera is connected', async () => {
    setup({ target: null })
    await flushPromises()
    expect(wrapper.find('[data-testid=cam]').exists()).toBe(true)
  })

  it('arrow keys switch source and the choice is remembered', async () => {
    setup()
    await radios()[1].trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(radios()[0].attributes('aria-checked')).toBe('true')
    expect(wrapper.find('[data-testid=cam]').exists()).toBe(true)
    expect(localStorage.getItem('nikon-gallery-source')).toBe('camera')
  })

  it('restores the remembered source', async () => {
    localStorage.setItem('nikon-gallery-source', 'camera')
    setup()
    await flushPromises()
    expect(radios()[0].attributes('aria-checked')).toBe('true')
  })

  it('an open= deep link switches to storage', async () => {
    localStorage.setItem('nikon-gallery-source', 'camera')
    setup()
    routeQuery.value = { open: 'a/b.jpg' }
    await flushPromises()
    expect(radios()[1].attributes('aria-checked')).toBe('true')
    routeQuery.value = {}
  })

  it('shows the camera for a saved storage choice when no storage is chosen, keeping the saved choice', async () => {
    localStorage.setItem('nikon-gallery-source', 'storage')
    setup({ target: null })
    await flushPromises()
    expect(wrapper.find('[data-testid=cam]').exists()).toBe(true)
    expect(localStorage.getItem('nikon-gallery-source')).toBe('storage')
  })

  it('re-reads the camera storage on every show, not only when it is missing', async () => {
    const { cam } = setup({ cards: [{ free_kb: 1 }] })
    await flushPromises()
    expect(cam.fetchStorage).toHaveBeenCalledTimes(1)
  })

  it('re-reads the camera storage when a kept-alive gallery is shown again', async () => {
    const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
    const cam = useCameraStore(pinia)
    cam.connected = true
    cam.storage = { cards: [{ free_kb: 1 }] }
    vi.spyOn(cam, 'fetchStorage').mockResolvedValue()
    const st = useStorageStore(pinia)
    st.loaded = true
    st.targetId = null
    const page = ref('gallery')
    const Host = {
      setup: () => () =>
        h(KeepAlive, null, [page.value === 'gallery' ? h(GalleryView) : h('div', { key: 'x' })]),
    }
    wrapper = mount(Host, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(cam.fetchStorage).toHaveBeenCalledTimes(1)
    page.value = 'other'
    await flushPromises()
    page.value = 'gallery'
    await flushPromises()
    expect(cam.fetchStorage).toHaveBeenCalledTimes(2)
  })
})
