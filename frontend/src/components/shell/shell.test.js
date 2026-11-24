import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { nextTick } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import { useJobsStore } from '@/stores/jobs'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import AppHeader from './AppHeader.vue'
import CameraGate from './CameraGate.vue'
import { jobSummary } from './jobSummary'
import ToastHost from './ToastHost.vue'
import JobsPanel from './JobsPanel.vue'
import ApiKeyPrompt from './ApiKeyPrompt.vue'

const getConfig = vi.fn()
vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { getConfig: (...a) => getConfig(...a) },
}))

const pinia = () => createTestingPinia({ stubActions: false, createSpy: vi.fn })

describe('AppHeader and camera chip', () => {
  const mountHeader = (p, activeTab = 'shoot') =>
    mount(AppHeader, { props: { activeTab }, global: { plugins: [p] }, attachTo: document.body })

  it('has four tabs (no Advanced) and marks the active one', () => {
    const p = pinia()
    useCameraStore().fetchStorage = vi.fn(async () => {})
    const w = mountHeader(p, 'gallery')
    const tabs = w.findAll('nav a')
    expect(tabs.map((t) => t.text())).toEqual(['Shoot', 'Time-lapse', 'Gallery', 'Settings'])
    expect(w.find('nav a[aria-current="page"]').text()).toBe('Gallery')
    w.unmount()
  })

  it('shows the camera state, battery, shots left and the job count', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.fetchStorage = vi.fn(async () => {})
    camera.connected = true
    camera.state = 'idle'
    camera.battery = { percent: 80 }
    camera.storage = { cards: [{ free_images: 1284, free_kb: 1024 * 1024 }] }
    useJobsStore().upsert({ id: 'a', kind: 'bulb', status: 'running', created: '1' })
    const w = mountHeader(p)
    expect(w.find('[data-test="state"]').text()).toBe('Connected')
    expect(w.find('[data-test="battery"]').text()).toContain('80%')
    expect(w.find('[data-test="shots"]').text()).toContain('1,284')
    expect(w.find('[data-test="jobs-count"]').text()).toBe('1')
    camera.leasedBy = 'timelapse'
    await nextTick()
    expect(w.find('[data-test="state"]').text()).toBe('Busy')
    w.unmount()
  })

  it('says No permission when connecting failed because the camera cannot be opened', () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.fetchStorage = vi.fn(async () => {})
    camera.lastError = Object.assign(new Error('x'), { code: 'CAMERA_PERMISSION_DENIED' })
    const w = mountHeader(p)
    expect(w.find('[data-test="state"]').text()).toBe('No permission')
    w.unmount()
  })

  it('connects from the chip when disconnected and toasts other failures', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.fetchStorage = vi.fn(async () => {})
    camera.connect = vi.fn(async () => {
      throw new Error('no camera')
    })
    const w = mountHeader(p)
    expect(w.find('[data-test="state"]').text()).toBe('Disconnected')
    await w.find('[data-test="chip"]').trigger('click')
    await flushPromises()
    expect(camera.connect).toHaveBeenCalled()
    expect(useToastsStore().items.at(-1).message).toBe('no camera')
    w.unmount()
  })

  it('opens the camera popover when connected; Esc closes it and Disconnect works', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.fetchStorage = vi.fn(async () => {})
    camera.disconnect = vi.fn(async () => {})
    camera.connected = true
    camera.state = 'idle'
    camera.model = 'D500'
    const w = mountHeader(p)
    await w.find('[data-test="chip"]').trigger('click')
    const pop = w.find('[data-test="camera-popover"]')
    expect(pop.exists()).toBe(true)
    expect(pop.find('[data-test="model"]').text()).toBe('D500')
    await pop.trigger('keydown', { key: 'Escape' })
    expect(w.find('[data-test="camera-popover"]').exists()).toBe(false)
    await w.find('[data-test="chip"]').trigger('click')
    await w.find('[data-test="toggle"]').trigger('click')
    expect(camera.disconnect).toHaveBeenCalled()
    w.unmount()
  })

  it('switches the layout from the header', async () => {
    const p = pinia()
    useCameraStore().fetchStorage = vi.fn(async () => {})
    const w = mountHeader(p)
    await w.find('[data-test="layout-touch"]').trigger('click')
    expect(document.documentElement.dataset.layout).toBe('touch')
    expect(w.find('[data-test="layout-touch"]').attributes('aria-pressed')).toBe('true')
    await w.find('[data-test="layout-desktop"]').trigger('click')
    expect(document.documentElement.dataset.layout).toBe('desktop')
    w.unmount()
  })
})

describe('CameraGate', () => {
  it('offers Connect when disconnected', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.connect = vi.fn(async () => {})
    const w = mount(CameraGate, { global: { plugins: [p] } })
    expect(w.text()).toContain('Camera not connected')
    await w.find('[data-test="gate-connect"]').trigger('click')
    expect(camera.connect).toHaveBeenCalled()
  })

  it('explains a permission failure with the udev commands and Try again', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.lastError = Object.assign(new Error("Camera found, but the app can't open it."), {
      code: 'CAMERA_PERMISSION_DENIED',
      details: { bus: '004', device: '004' },
    })
    camera.connect = vi.fn(async () => {})
    const w = mount(CameraGate, { global: { plugins: [p] } })
    expect(w.find('[role="alert"]').text()).toContain("Camera found, but the app can't open it")
    expect(w.find('[role="alert"]').text()).toContain('bus 004, device 004')
    expect(w.find('[data-test="udev-commands"]').text()).toContain('udevadm control --reload-rules')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Try again')
      .trigger('click')
    expect(camera.connect).toHaveBeenCalled()
    expect(w.text()).not.toContain('Camera not connected')
  })
})

describe('ToastHost', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('auto-dismisses info but keeps errors until dismissed', async () => {
    const p = pinia()
    const toasts = useToastsStore()
    const w = mount(ToastHost, { global: { plugins: [p] } })
    toasts.info('hello')
    toasts.error('bad thing')
    await nextTick()
    expect(w.findAll('[data-test="toast"]')).toHaveLength(2)
    vi.advanceTimersByTime(10000)
    await nextTick()
    const left = w.findAll('[data-test="toast"]')
    expect(left).toHaveLength(1)
    expect(left[0].text()).toContain('bad thing')
    expect(left[0].attributes('role')).toBe('alert')
    await left[0].find('button').trigger('click')
    expect(w.findAll('[data-test="toast"]')).toHaveLength(0)
  })

  it('shows code and request id when present', async () => {
    const p = pinia()
    const toasts = useToastsStore()
    const w = mount(ToastHost, { global: { plugins: [p] } })
    toasts.push('error', 'x', 0)
    toasts.items[0].code = 'E_BUSY'
    toasts.items[0].requestId = 'req-1'
    await nextTick()
    expect(w.find('[data-test="detail"]').text()).toContain('E_BUSY')
    expect(w.find('[data-test="detail"]').text()).toContain('req-1')
  })

  it('shows camera-reported text and the manual note as secondary text', async () => {
    const p = pinia()
    const toasts = useToastsStore()
    const w = mount(ToastHost, { global: { plugins: [p] } })
    toasts.error({
      code: 'X',
      message: 'The camera refused live view.',
      details: {
        prohibit: 'Battery exhausted',
        nikon_manual: 'D500 manual p.35 (Battery Level): x',
      },
    })
    await nextTick()
    expect(w.find('[data-test="reported"]').text()).toBe('Camera reports: Battery exhausted')
    expect(w.find('[data-test="manual"]').text()).toBe('Nikon D500 manual p.35 (Battery Level): x')
  })
})

describe('JobsPanel', () => {
  it('lists jobs with progress, cancels with two clicks and toasts on completion', async () => {
    const p = pinia()
    const jobs = useJobsStore()
    const toasts = useToastsStore()
    jobs.cancel = vi.fn(async () => {})
    jobs.upsert({
      id: 'j1',
      kind: 'render-video',
      status: 'running',
      progress: 0.4,
      message: 'encoding',
      created: '1',
    })
    const w = mount(JobsPanel, {
      props: { open: true },
      global: { plugins: [p] },
      attachTo: document.body,
    })
    await nextTick()
    const row = document.body.querySelector('[data-test="job"]')
    expect(row.textContent).toContain('Video render')
    expect(row.textContent).toContain('Running')
    expect(row.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')).toBe('40')
    const cancel = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('Cancel'))
    cancel.click()
    await nextTick()
    cancel.click()
    expect(jobs.cancel).toHaveBeenCalledWith('j1')

    jobs.upsert({ id: 'j1', kind: 'render-video', status: 'completed', progress: 1, created: '1' })
    await nextTick()
    expect(toasts.items.at(-1).message).toBe('Video render finished')
    jobs.upsert({ id: 'j2', kind: 'zip', status: 'failed', error: 'oops', created: '2' })
    await nextTick()
    expect(toasts.items.some((t) => t.kind === 'error')).toBe(false) // first seen finished: no toast
    w.unmount()
  })
})

describe('jobSummary', () => {
  it('writes readable summaries and never prints raw result keys', () => {
    expect(jobSummary({ error: 'oops' })).toBe('oops')
    expect(jobSummary({ result: { file_count: 10, folder: 'stack_1' } })).toBe(
      '10 files · in stack_1',
    )
    expect(jobSummary({ result: { output: 'videos/a.mp4' } })).toBe('Saved a.mp4')
    expect(jobSummary({ result: { copied: 1, failed: 2 } })).toBe('1 file copied · 2 failed')
    expect(jobSummary({ result: { weird_key: 'x' } })).toBe('')
  })
})

describe('ApiKeyPrompt', () => {
  beforeEach(() => {
    getConfig.mockReset()
    localStorage.clear()
  })

  it('is shown only when a key is required and stores a verified key', async () => {
    const p = pinia()
    const auth = useAuthStore()
    const events = useEventsStore()
    events.restart = vi.fn()
    auth.fetchInfo = vi.fn(async () => {})
    getConfig.mockResolvedValue({})
    const w = mount(ApiKeyPrompt, { global: { plugins: [p] }, attachTo: document.body })
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
    auth.markRequired()
    await nextTick()
    const input = document.body.querySelector('input')
    input.value = 'abc'
    input.dispatchEvent(new Event('input'))
    document.body.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    expect(getConfig).toHaveBeenCalled()
    expect(auth.apiKey).toBe('abc')
    expect(auth.required).toBe(false)
    w.unmount()
  })

  it('rejects a bad key and stays open', async () => {
    const p = pinia()
    const auth = useAuthStore()
    getConfig.mockRejectedValue(Object.assign(new Error('nope'), { status: 401 }))
    const w = mount(ApiKeyPrompt, { global: { plugins: [p] }, attachTo: document.body })
    auth.markRequired()
    await nextTick()
    const input = document.body.querySelector('input')
    input.value = 'bad'
    input.dispatchEvent(new Event('input'))
    document.body.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    expect(auth.apiKey).toBe('')
    expect(auth.required).toBe(true)
    expect(document.body.querySelector('[data-test="error"]')).not.toBeNull()
    w.unmount()
  })
})
