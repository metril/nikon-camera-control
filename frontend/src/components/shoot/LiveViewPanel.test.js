import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { defineComponent, h, KeepAlive, ref, nextTick } from 'vue'

const { sockets } = vi.hoisted(() => ({ sockets: [] }))
vi.mock('@/api/ws.js', async (importOriginal) => {
  const { ref } = await import('vue')
  return {
    ...(await importOriginal()),
    createLiveViewSocket: (handlers) => {
      const status = ref('closed')
      const s = {
        status,
        handlers,
        start: vi.fn(() => (status.value = 'open')),
        close: vi.fn(() => (status.value = 'closed')),
      }
      sockets.push(s)
      return s
    },
  }
})

import LiveViewPanel from './LiveViewPanel.vue'
import { useCameraStore } from '@/stores/camera'
import { useLiveViewStore } from '@/stores/liveview'
import { useToastsStore } from '@/stores/toasts'

let n
function setup(connected = true) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const camera = useCameraStore()
  camera.connected = connected
  const lv = useLiveViewStore()
  vi.spyOn(lv, 'fetchStatus').mockResolvedValue()
  vi.spyOn(lv, 'start').mockResolvedValue()
  vi.spyOn(lv, 'stop').mockResolvedValue()
  return { pinia, camera, lv }
}
async function started(wrapper) {
  await wrapper.find('[data-testid="lv-start"]').trigger('click')
  await flushPromises()
  return sockets.at(-1)
}
const status = (s, o = {}) =>
  s.handlers.onStatus({
    type: 'status',
    phase: 'streaming',
    camera_state: 'liveview',
    fps: 9.5,
    ...o,
  })

beforeEach(() => {
  sockets.length = 0
  n = 0
  vi.stubGlobal('createImageBitmap', undefined)
  URL.createObjectURL = vi.fn(() => `blob:${++n}`)
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('LiveViewPanel', () => {
  it('shows an empty state with Connect when disconnected', () => {
    const { pinia, camera } = setup(false)
    vi.spyOn(camera, 'connect').mockResolvedValue()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    expect(w.text()).toContain('Camera not connected')
    expect(w.find('[data-testid="lv-start"]').attributes('disabled')).toBeDefined()
  })

  it('revokes the previous object URL on each frame and the last on unmount', async () => {
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    expect(s.start).toHaveBeenCalled()
    s.handlers.onFrame(new ArrayBuffer(4))
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    s.handlers.onFrame(new ArrayBuffer(4))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:1')
    s.handlers.onFrame(new ArrayBuffer(4))
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:2')
    w.unmount()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:3')
    expect(s.close).toHaveBeenCalled()
  })

  it('revokes the URL when the image fails to load', async () => {
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    s.handlers.onFrame(new ArrayBuffer(4))
    await w.find('img').trigger('error')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:1')
  })

  it('closes the socket when deactivated and reopens on activate', async () => {
    const { pinia } = setup()
    const show = ref(true)
    const Host = defineComponent({
      render: () =>
        h(KeepAlive, null, { default: () => (show.value ? h(LiveViewPanel) : h('div')) }),
    })
    const w = mount(Host, { global: { plugins: [pinia] } })
    const s = await started(w)
    expect(s.start).toHaveBeenCalledTimes(1)
    show.value = false
    await nextTick()
    await flushPromises()
    expect(s.close).toHaveBeenCalled()
    show.value = true
    await nextTick()
    await flushPromises()
    expect(s.start).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('closes after the tab is hidden for a while and reconnects on return', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    const vis = (state) => {
      Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
      document.dispatchEvent(new Event('visibilitychange'))
    }
    vis('hidden')
    await vi.advanceTimersByTimeAsync(6000)
    expect(s.close).toHaveBeenCalled()
    vis('visible')
    await flushPromises()
    expect(s.start).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('shows the stale overlay after 3 s without frames while live', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    expect(w.find('[data-testid="lv-state"]').text()).toBe('Live')
    expect(w.find('[data-testid="lv-stale"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(3100)
    expect(w.find('[data-testid="lv-stale"]').exists()).toBe(true)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    expect(w.find('[data-testid="lv-stale"]').exists()).toBe(false)
    w.unmount()
  })

  it('reflects paused status and fps from socket status', async () => {
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s, { client_frames_dropped: 2 })
    await nextTick()
    expect(w.text()).toContain('9.5 fps')
    expect(w.text()).toContain('2 dropped')
    status(s, { phase: 'waiting', reason: 'capturing' })
    await nextTick()
    expect(w.find('[data-testid="lv-state"]').text()).toBe('Paused: capturing')
    w.unmount()
  })

  it('toasts when Start fails and stays stopped', async () => {
    const { pinia, lv } = setup()
    lv.start.mockRejectedValue(new Error('nope'))
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    await w.find('[data-testid="lv-start"]').trigger('click')
    await flushPromises()
    expect(useToastsStore().items.at(-1).message).toBe('nope')
    expect(sockets[0].start).not.toHaveBeenCalled()
  })
})
