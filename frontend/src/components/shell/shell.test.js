import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { nextTick } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import { useJobsStore } from '@/stores/jobs'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import StatusBar from './StatusBar.vue'
import ToastHost from './ToastHost.vue'
import JobsPanel from './JobsPanel.vue'
import ApiKeyPrompt from './ApiKeyPrompt.vue'

const getConfig = vi.fn()
vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { getConfig: (...a) => getConfig(...a) },
}))

const pinia = () => createTestingPinia({ stubActions: false, createSpy: vi.fn })

describe('StatusBar', () => {
  it('shows model, battery, free storage, lease and connect action', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.fetchStorage = vi.fn(async () => {})
    camera.connect = vi.fn(async () => {})
    camera.model = 'D500'
    camera.battery = { percent: 80 }
    camera.storage = { cards: [{ free_kb: 1024 * 1024 }] }
    camera.leasedBy = 'timelapse'
    camera.state = 'disconnected'
    const w = mount(StatusBar, { global: { plugins: [p] } })
    expect(w.find('[data-test="model"]').text()).toBe('D500')
    expect(w.find('[data-test="battery"]').text()).toContain('80%')
    expect(w.find('[data-test="storage"]').text()).toContain('1.0 GB')
    expect(w.find('[data-test="lease"]').text()).toBe('Busy: timelapse')
    await w.find('[data-test="toggle"]').trigger('click')
    expect(camera.connect).toHaveBeenCalled()
  })

  it('toasts when connecting fails', async () => {
    const p = pinia()
    const camera = useCameraStore()
    camera.connect = vi.fn(async () => {
      throw new Error('no camera')
    })
    const w = mount(StatusBar, { global: { plugins: [p] } })
    await w.find('[data-test="toggle"]').trigger('click')
    await flushPromises()
    expect(useToastsStore().items.at(-1).message).toBe('no camera')
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
})

describe('JobsPanel', () => {
  it('lists jobs with progress, cancels with two clicks and toasts on completion', async () => {
    const p = pinia()
    const jobs = useJobsStore()
    const toasts = useToastsStore()
    jobs.cancel = vi.fn(async () => {})
    jobs.upsert({
      id: 'j1',
      kind: 'render',
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
    expect(row.textContent).toContain('render')
    expect(row.querySelector('[role="progressbar"]').getAttribute('aria-valuenow')).toBe('40')
    const cancel = [...row.querySelectorAll('button')].find((b) => b.textContent.includes('Cancel'))
    cancel.click()
    await nextTick()
    cancel.click()
    expect(jobs.cancel).toHaveBeenCalledWith('j1')

    jobs.upsert({ id: 'j1', kind: 'render', status: 'completed', progress: 1, created: '1' })
    await nextTick()
    expect(toasts.items.at(-1).message).toContain('Job finished')
    jobs.upsert({ id: 'j2', kind: 'zip', status: 'failed', error: 'oops', created: '2' })
    await nextTick()
    expect(toasts.items.some((t) => t.kind === 'error')).toBe(false) // first seen finished: no toast
    w.unmount()
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
