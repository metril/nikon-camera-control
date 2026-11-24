import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useSettingsStore } from '@/stores/settings'
import { useShootStore } from '@/stores/shoot'
import { mountCard } from '@/components/shoot/testing'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {}, downloadBlob: vi.fn() }))
vi.mock('@/components/shoot/LiveViewPanel.vue', () => ({
  default: defineComponent({
    name: 'LiveViewPanel',
    render: () => h('div', { 'data-test': 'lv' }),
  }),
}))
import ShootView from './ShootView.vue'

let wrapper
function setup(opts = {}) {
  const r = mountCard(ShootView, {
    ...opts,
    attachTo: document.body,
    setup: () => {
      const st = useSettingsStore()
      st.common = [
        {
          name: 'f-number',
          label: 'Aperture',
          value: '5.6',
          choices: ['4', '5.6'],
          writable: true,
        },
      ]
      st.fetchCommon = vi.fn().mockResolvedValue()
      useCaptureStore().loadRecent = vi.fn().mockResolvedValue([])
      useShootStore().press = vi.fn()
    },
  })
  wrapper = r.wrapper
  return r
}
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ''
})
const press = (key, target = document.body, init = {}) =>
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }),
  )

describe('ShootView', () => {
  it('Space presses the shutter, but not from a focused button, input or open dialog', async () => {
    setup()
    const shoot = useShootStore()
    press(' ')
    expect(shoot.press).toHaveBeenCalledTimes(1)
    press(' ', wrapper.find('button').element)
    expect(shoot.press).toHaveBeenCalledTimes(1)
    const dialog = document.createElement('div')
    dialog.setAttribute('aria-modal', 'true')
    document.body.append(dialog)
    press(' ')
    expect(shoot.press).toHaveBeenCalledTimes(1)
    dialog.remove()
    press(' ', document.body, { ctrlKey: true })
    expect(shoot.press).toHaveBeenCalledTimes(1)
  })

  it('stops listening once the view is unmounted', () => {
    setup()
    const shoot = useShootStore()
    wrapper.unmount()
    press(' ')
    expect(shoot.press).not.toHaveBeenCalled()
  })

  it('A, S, I and E jump to aperture, shutter, ISO and exposure compensation', async () => {
    setup()
    const spy = vi.spyOn(wrapper.findComponent({ name: 'ExposureStrip' }).vm, 'focusCell')
    press('a')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.find('[data-k="aperture"]').element)
    spy.mockRestore()
  })

  it('shows one connect state instead of the live view when the camera is not connected', () => {
    setup({ connected: false })
    expect(wrapper.find('[data-test="lv"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="gate-connect"]')).toHaveLength(1)
    expect(wrapper.text().match(/Camera not connected/g)).toHaveLength(1)
    useCameraStore().connected = true
  })

  it('shows the live view when connected', () => {
    setup()
    expect(wrapper.find('[data-test="lv"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="gate-connect"]').exists()).toBe(false)
  })

  it('re-reads the exposure strip on show and every 5 s while idle, not while busy', () => {
    vi.useFakeTimers()
    try {
      setup()
      const camera = useCameraStore()
      const st = useSettingsStore()
      st.refreshExposure = vi.fn().mockResolvedValue()
      camera.connected = true
      camera.state = 'idle'
      vi.advanceTimersByTime(5000)
      expect(st.refreshExposure).toHaveBeenCalledTimes(1)
      camera.state = 'capturing'
      vi.advanceTimersByTime(5000)
      expect(st.refreshExposure).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('skips the poll while leased and drops it once the body announces property events', () => {
    vi.useFakeTimers()
    try {
      setup()
      const camera = useCameraStore()
      const st = useSettingsStore()
      st.refreshExposure = vi.fn().mockResolvedValue()
      camera.leasedBy = 'recording'
      vi.advanceTimersByTime(5000)
      expect(st.refreshExposure).not.toHaveBeenCalled()
      camera.leasedBy = null
      camera.propertyEvents = true
      vi.advanceTimersByTime(10000)
      expect(st.refreshExposure).not.toHaveBeenCalled()
      document.dispatchEvent(new Event('visibilitychange')) // shown again: one refresh
      expect(st.refreshExposure).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })
})
