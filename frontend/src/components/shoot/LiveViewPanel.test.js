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
        restart: vi.fn(),
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
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'
import { useFocusStore } from '@/stores/focus'

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

  it('restarts the socket when the API key changes or is entered after a 4401', async () => {
    const { pinia } = setup()
    const auth = useAuthStore()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    auth.setKey('new-key')
    await flushPromises()
    expect(s.restart).toHaveBeenCalledTimes(1)
    s.status.value = 'unauthorized'
    auth.markRequired()
    await flushPromises()
    auth.setKey('new-key') // same key re-entered: required flips back to false
    await flushPromises()
    expect(s.restart).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('shows a terminal origin-not-allowed state', async () => {
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    s.status.value = 'forbidden'
    await flushPromises()
    expect(w.text()).toContain('origin is not allowed')
    expect(w.text()).toContain('Settings › General › Allowed origins')
    expect(w.text()).not.toContain('cors_origins')
    w.unmount()
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
    expect(w.find('[data-testid="lv-state"]').text()).toBe('Live · 9.5 fps')
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
    expect(w.text()).toContain('Live · 9.5 fps')
    expect(w.text()).toContain('2 dropped')
    status(s, { phase: 'waiting', reason: 'camera_capturing' })
    await nextTick()
    expect(w.find('[data-testid="lv-state"]').text()).toBe('Paused: camera capturing')
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

  it('shows the tool pill with the grid cycling and persisted tool toggles', async () => {
    const { pinia, lv } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    const bar = w.find('[data-testid="lv-toolbar"]')
    for (const l of ['Thirds', 'Histogram', 'Clipping', 'Peaking', 'Loupe', 'Last shot overlay'])
      expect(bar.text()).toContain(l)
    expect(bar.text()).not.toMatch(/onion/i)
    await w.find('[data-testid="lv-tool-grid"]').trigger('click')
    expect(w.find('[data-testid="lv-tool-grid"]').text()).toBe('Golden')
    await w.find('[data-testid="lv-tool-grid"]').trigger('click')
    await w.find('[data-testid="lv-tool-grid"]').trigger('click')
    expect(w.find('[data-testid="lv-tool-grid"]').text()).toBe('Grid off')
    expect(w.find('[data-testid="lv-tool-grid"]').attributes('aria-pressed')).toBe('false')
    expect(w.find('[data-testid="lv-hist"]').exists()).toBe(true)
    await w.find('[data-testid="lv-tool-hist"]').trigger('click')
    expect(lv.tools.hist).toBe(false)
    expect(w.find('[data-testid="lv-hist"]').exists()).toBe(false)
    w.unmount()
  })

  it('focus pill drives manual steps and autofocus, with a Focus locked badge', async () => {
    const { pinia } = setup()
    const focus = useFocusStore()
    vi.spyOn(focus, 'manual').mockResolvedValue()
    vi.spyOn(focus, 'autofocus').mockResolvedValue({ focused: true })
    vi.spyOn(focus, 'setPoint').mockResolvedValue()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    await w.find('[data-testid="lv-focus-near-large"]').trigger('click')
    await w.find('[data-testid="lv-focus-far-small"]').trigger('click')
    expect(focus.manual).toHaveBeenNthCalledWith(1, -1000)
    expect(focus.manual).toHaveBeenNthCalledWith(2, 150)
    await w.find('[data-testid="lv-autofocus"]').trigger('click')
    await flushPromises()
    expect(focus.autofocus).toHaveBeenCalled()
    expect(focus.setPoint).not.toHaveBeenCalled()
    expect(w.find('[data-testid="lv-state"]').text()).toBe('Focus locked')
    w.unmount()
  })

  it('focus limit: no toast, that direction disabled, re-enabled by the opposite step', async () => {
    const { pinia } = setup()
    const focus = useFocusStore()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    const limitErr = Object.assign(new Error('The lens is at its closest focus'), {
      status: 409,
      code: 'FOCUS_LIMIT',
    })
    vi.spyOn(focus, 'manual').mockRejectedValueOnce(limitErr).mockResolvedValue()
    const near = w.find('[data-testid="lv-focus-near-small"]')
    await near.trigger('click')
    await flushPromises()
    expect(useToastsStore().items).toHaveLength(0)
    expect(near.attributes('aria-disabled')).toBe('true')
    expect(near.attributes('title')).toBe('Closest focus')
    expect(w.find('[data-testid="lv-focus-near-large"]').attributes('aria-disabled')).toBe('true')
    expect(w.find('[data-testid="lv-focus-far-small"]').attributes('aria-disabled')).toBeUndefined()
    await near.trigger('click') // blocked locally
    expect(focus.manual).toHaveBeenCalledTimes(1)
    await w.find('[data-testid="lv-focus-far-small"]').trigger('click')
    await flushPromises()
    expect(near.attributes('aria-disabled')).toBeUndefined()
    w.unmount()
  })

  it('a non-limit focus step error still toasts', async () => {
    const { pinia } = setup()
    const focus = useFocusStore()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    vi.spyOn(focus, 'manual').mockRejectedValue(new Error('boom'))
    await w.find('[data-testid="lv-focus-near-small"]').trigger('click')
    await flushPromises()
    expect(useToastsStore().items.at(-1).message).toBe('boom')
    expect(
      w.find('[data-testid="lv-focus-near-small"]').attributes('aria-disabled'),
    ).toBeUndefined()
    w.unmount()
  })

  it('manual mode: tap only moves the AF point, no autofocus; steps follow the config', async () => {
    const { pinia } = setup()
    const focus = useFocusStore()
    useConfigStore().config = { camera: { focus_step_small: 20, focus_step_large: 300 } }
    vi.spyOn(focus, 'manual').mockResolvedValue()
    vi.spyOn(focus, 'autofocus').mockResolvedValue({ focused: true })
    vi.spyOn(focus, 'setPoint').mockResolvedValue()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    await w.find('[data-testid="lv-focus-mode"]').trigger('click')
    expect(w.find('[data-testid="lv-autofocus"]').exists()).toBe(false)
    expect(localStorage.getItem('focusMode')).toBe('manual')
    const ov = w.find('[data-testid="lv-overlay"]')
    await ov.trigger('pointerdown', { clientX: 0, clientY: 0 })
    await ov.trigger('pointerup', { clientX: 0, clientY: 0 })
    await flushPromises()
    expect(focus.setPoint).toHaveBeenCalledTimes(1)
    expect(focus.autofocus).not.toHaveBeenCalled()
    await w.find('[data-testid="lv-focus-far-large"]').trigger('click')
    expect(focus.manual).toHaveBeenCalledWith(300)
    localStorage.removeItem('focusMode')
    w.unmount()
  })

  it('tap moves the AF point, then autofocuses; a point error still autofocuses', async () => {
    const { pinia } = setup()
    const focus = useFocusStore()
    vi.spyOn(focus, 'setPoint').mockResolvedValue()
    vi.spyOn(focus, 'autofocus').mockResolvedValue({ focused: true })
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    const ov = w.find('[data-testid="lv-overlay"]')
    await ov.trigger('pointerdown', { clientX: 0, clientY: 0 })
    await ov.trigger('pointerup', { clientX: 0, clientY: 0 })
    await flushPromises()
    expect(focus.setPoint).toHaveBeenCalledTimes(1)
    const [x, y] = focus.setPoint.mock.calls[0]
    expect(x).toBeGreaterThanOrEqual(0)
    expect(x).toBeLessThanOrEqual(1)
    expect(y).toBeLessThanOrEqual(1)
    expect(focus.autofocus).toHaveBeenCalledTimes(1)
    focus.setPoint.mockRejectedValue(new Error('no widget'))
    await ov.trigger('pointerdown', { clientX: 0, clientY: 0 })
    await ov.trigger('pointerup', { clientX: 0, clientY: 0 })
    await flushPromises()
    expect(focus.autofocus).toHaveBeenCalledTimes(2)
    expect(useToastsStore().items.some((t) => t.kind === 'warn')).toBe(true)
    focus.setPoint.mockClear()
    focus.setPoint.mockRejectedValue(Object.assign(new Error('x'), { status: 501 }))
    for (let i = 0; i < 2; i++) {
      await ov.trigger('pointerdown', { clientX: 0, clientY: 0 })
      await ov.trigger('pointerup', { clientX: 0, clientY: 0 })
      await flushPromises()
    }
    expect(focus.setPoint).toHaveBeenCalledTimes(1) // 501 remembered: not retried
    expect(focus.autofocus).toHaveBeenCalledTimes(4)
    useCameraStore().connectedAt = '2026-01-01T00:00:00Z' // reconnect: the body is tried again
    await nextTick()
    await ov.trigger('pointerdown', { clientX: 0, clientY: 0 })
    await ov.trigger('pointerup', { clientX: 0, clientY: 0 })
    await flushPromises()
    expect(focus.setPoint).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('labels the fullscreen button', async () => {
    const { pinia } = setup()
    const w = mount(LiveViewPanel, { global: { plugins: [pinia] } })
    const s = await started(w)
    status(s)
    s.handlers.onFrame(new ArrayBuffer(4))
    await nextTick()
    expect(w.find('[data-testid="lv-fullscreen"]').attributes('aria-label')).toBe('Fullscreen')
    w.unmount()
  })
})
