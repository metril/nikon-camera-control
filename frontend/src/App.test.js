import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { useCameraStore } from '@/stores/camera'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import { resetLayoutMode, useLayoutMode } from '@/composables/useLayoutMode'

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
  const w = mount(App, { global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return { w, camera }
}

describe('App shell', () => {
  beforeEach(() => {
    location.hash = '#/shoot'
    localStorage.clear()
    resetLayoutMode()
    log.length = 0
    document.body.innerHTML = ''
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

  it('does not know an Advanced tab: an old link falls back to Shoot', async () => {
    location.hash = '#/advanced'
    const { w } = await setup()
    expect(w.find('[data-view="shoot"]').exists()).toBe(true)
    expect(w.findAll('header nav a').map((a) => a.text())).toEqual([
      'Shoot',
      'Time-lapse',
      'Gallery',
      'Settings',
    ])
    w.unmount()
  })

  it('? opens the shortcuts modal and hotkeys are suspended while it is open', async () => {
    const { w } = await setup()
    press('?')
    await flushPromises()
    const dialog = document.body.querySelector('[role="dialog"]')
    expect(dialog.textContent).toContain('Take a photo')
    expect(dialog.textContent).toContain('Space')
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
    expect(a.attributes('href')).toBe('#/settings?section=api-key')
    expect(a.text()).toContain('No API key set')
    w.unmount()
  })

  it('shows a red stripe when disconnected, amber when busy and none when ready', async () => {
    const { w, camera } = await setup()
    const stripe = () => w.find('[data-test="stripe"]').classes()
    expect(stripe()).not.toContain('off')
    expect(stripe()).not.toContain('busy')
    camera.leasedBy = 'bulb'
    await flushPromises()
    expect(stripe()).toContain('busy')
    camera.leasedBy = null
    camera.reset()
    await flushPromises()
    expect(stripe()).toContain('off')
    w.unmount()
  })

  it('touch layout keeps the section tabs in the header and has no bottom bar', async () => {
    const { w } = await setup()
    useLayoutMode().setPref('touch')
    await flushPromises()
    expect(document.documentElement.dataset.layout).toBe('touch')
    expect(w.find('[data-test="bottomnav"]').exists()).toBe(false)
    const tabs = w.find('[data-test="header"] nav[aria-label="Primary"]')
    expect(tabs.findAll('a').map((a) => a.text())).toEqual([
      'Shoot',
      'Time-lapse',
      'Gallery',
      'Settings',
    ])
    await tabs.findAll('a')[2].trigger('click')
    expect(location.hash).toBe('#/gallery')
    w.unmount()
  })

  it('explains a rejected origin and points to Settings', async () => {
    const { w } = await setup()
    useEventsStore().status = 'forbidden'
    await flushPromises()
    expect(w.find('[data-test="origin-blocked"]').text()).toContain('Allowed origins')
    w.unmount()
  })
})
