import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { createTestingPinia } from '@pinia/testing'

const { setKioskDisplay } = vi.hoisted(() => ({ setKioskDisplay: vi.fn(async () => ({})) }))
vi.mock('@/api', async (orig) => ({ ...(await orig()), api: { setKioskDisplay } }))

import KioskSleepOverlay from './KioskSleepOverlay.vue'
import { useConfigStore } from '@/stores/config'

const clicked = vi.fn()
const Host = defineComponent({
  render: () =>
    h('div', [h('button', { id: 'shutter', onClick: clicked }, 'shoot'), h(KioskSleepOverlay)]),
})

let w
async function mountApp({ url = '?layout=touch&kiosk=1', minutes = 5 } = {}) {
  window.history.replaceState({}, '', `/${url}`)
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const config = useConfigStore()
  config.config = { kiosk: { scale: 'auto', sleep_after_min: minutes } }
  config.fetch = vi.fn(async () => {})
  w = mount(Host, { global: { plugins: [pinia] }, attachTo: document.body })
  await nextTick()
  return config
}
const fire = (type, target = document.body) =>
  target.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }))
const overlay = () => document.querySelector('[data-test="kiosk-sleep"]')
const min = async (n) => {
  vi.advanceTimersByTime(n * 60_000)
  await nextTick()
}

describe('kiosk screen sleep', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })
  afterEach(() => {
    w?.unmount()
    vi.useRealTimers()
    window.history.replaceState({}, '', '/')
  })

  it('never runs without kiosk=1, even in the touch layout', async () => {
    await mountApp({ url: '?layout=touch' })
    await min(120)
    expect(overlay()).toBeNull()
    expect(setKioskDisplay).not.toHaveBeenCalled()
  })

  it('shows the overlay after the timeout and posts off', async () => {
    await mountApp()
    await min(4)
    expect(overlay()).toBeNull()
    await min(1)
    expect(overlay()).not.toBeNull()
    expect(setKioskDisplay).toHaveBeenCalledWith({ body: { on: false } })
  })

  it('pointerdown, keydown and wheel restart the timer', async () => {
    await mountApp()
    for (const t of ['pointerdown', 'keydown', 'wheel']) {
      await min(4)
      fire(t)
    }
    await min(4)
    expect(overlay()).toBeNull()
    await min(1)
    expect(overlay()).not.toBeNull()
  })

  it('stays awake when the setting is 0', async () => {
    await mountApp({ minutes: 0 })
    await min(1440)
    expect(overlay()).toBeNull()
  })

  it('swallows the waking tap, posts on and restarts the timer', async () => {
    await mountApp()
    await min(5)
    fire('pointerdown', overlay())
    expect(setKioskDisplay).toHaveBeenLastCalledWith({ body: { on: true } })
    fire('pointerup', overlay())
    fire('click', overlay()) // the click that follows the tap lands on the overlay
    expect(clicked).not.toHaveBeenCalled()
    await min(1)
    expect(overlay()).toBeNull()
    document.getElementById('shutter').click()
    expect(clicked).toHaveBeenCalledTimes(1)
    await min(5)
    expect(overlay()).not.toBeNull() // timer restarted
  })

  it('applies a changed setting live', async () => {
    const config = await mountApp({ minutes: 60 })
    await min(10)
    config.config = { kiosk: { sleep_after_min: 1 } }
    await nextTick()
    await min(1)
    expect(overlay()).not.toBeNull()
  })

  it('wakes when the setting is switched to 0 while asleep', async () => {
    const config = await mountApp()
    await min(5)
    config.config = { kiosk: { sleep_after_min: 0 } }
    await nextTick()
    expect(overlay()).toBeNull()
    expect(setKioskDisplay).toHaveBeenLastCalledWith({ body: { on: true } })
  })
})
