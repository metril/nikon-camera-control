import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useAuthStore } from '@/stores/auth'

const { log, view } = await vi.hoisted(async () => {
  const { defineComponent, h, onActivated, onDeactivated } = await import('vue')
  const log = []
  const view = (name) =>
    defineComponent({
      name,
      setup() {
        onActivated(() => log.push(`${name}:on`))
        onDeactivated(() => log.push(`${name}:off`))
        return () => h('div', { 'data-view': name }, h('button', { id: `${name}-btn` }, 'b'))
      },
    })
  return { log, view }
})
vi.mock('@/views/ShootView.vue', () => ({ default: view('shoot') }))
vi.mock('@/views/TimelapseView.vue', () => ({ default: view('timelapse') }))
vi.mock('@/views/GalleryView.vue', () => ({ default: view('gallery') }))
vi.mock('@/views/AdvancedView.vue', () => ({ default: view('advanced') }))
vi.mock('@/views/SettingsView.vue', () => ({ default: view('settings') }))
vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {} }))

import App from './App.vue'

const press = (key, target = document.body) =>
  target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))

async function setup() {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const camera = useCameraStore()
  camera.fetchStorage = vi.fn(async () => {})
  camera.state = 'idle'
  camera.connected = true
  const capture = useCaptureStore()
  capture.capture = vi.fn(async () => {})
  const w = mount(App, { global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return { w, camera, capture }
}

describe('App shell', () => {
  beforeEach(() => {
    location.hash = '#/shoot'
    localStorage.clear()
    log.length = 0
    document.body.innerHTML = ''
  })

  it('Space captures only on the Shoot tab and not from a focused button', async () => {
    const { w, capture } = await setup()
    press(' ')
    expect(capture.capture).toHaveBeenCalledTimes(1)
    const btn = w.find('#shoot-btn').element
    press(' ', btn)
    expect(capture.capture).toHaveBeenCalledTimes(1)
    press('g')
    await flushPromises()
    press(' ')
    expect(capture.capture).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('Space also captures while live view is running (regression)', async () => {
    const { w, camera, capture } = await setup()
    camera.state = 'liveview'
    press(' ')
    expect(capture.capture).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('g/t switch tabs, update the hash and keep views alive with activation hooks', async () => {
    const { w } = await setup()
    press('g')
    await flushPromises()
    expect(location.hash).toBe('#/gallery')
    expect(w.find('[data-view="gallery"]').exists()).toBe(true)
    press('t')
    await flushPromises()
    expect(location.hash).toBe('#/timelapse')
    expect(log).toContain('shoot:off')
    expect(log).toContain('gallery:off')
    log.length = 0
    press('g')
    await flushPromises()
    expect(log).toEqual(['timelapse:off', 'gallery:on'])
    w.unmount()
  })

  it('? opens the shortcuts modal and hotkeys are suspended while it is open', async () => {
    const { w } = await setup()
    press('?')
    await flushPromises()
    expect(document.body.querySelector('[role="dialog"]').textContent).toContain('Capture')
    press('g')
    await flushPromises()
    expect(location.hash).toBe('#/shoot')
    w.unmount()
  })

  it('warns when auth is disabled and links to settings', async () => {
    const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
    useAuthStore().authEnabled = false
    useCameraStore().fetchStorage = vi.fn(async () => {})
    const w = mount(App, { global: { plugins: [pinia] } })
    const a = w.find('[data-test="no-key-warning"]')
    expect(a.attributes('href')).toBe('#/settings')
    expect(a.text()).toContain('No API key set')
    w.unmount()
  })

  it('scrolls the active tab into view in the horizontally scrollable tab bar', async () => {
    const spy = vi.fn()
    Element.prototype.scrollIntoView = spy
    const { w } = await setup()
    spy.mockClear()
    press('g')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith({ inline: 'center', block: 'nearest' })
    expect(spy.mock.contexts.at(-1).textContent).toContain('Gallery')
    w.unmount()
  })
})
