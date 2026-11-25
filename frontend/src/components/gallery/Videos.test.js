import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import Videos from './Videos.vue'
import { useVideosStore } from '@/stores/videos'
import { useSessionsStore } from '@/stores/sessions'
import { useToastsStore } from '@/stores/toasts'
import { useAuthStore } from '@/stores/auth'
import { useStorageStore } from '@/stores/storage'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { downloadVideo: vi.fn().mockResolvedValue(new Blob(['v'])) },
}))

const vid = {
  session_id: 's1',
  name: 'out.mp4',
  path: 's1/out.mp4',
  size: 1048576,
  created: '2026-01-01T00:00:00Z',
  duration_s: 65,
  fps: 24,
  codec: 'libx264',
}
let wrapper
function setup(items = [vid]) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const v = useVideosStore(pinia)
  vi.spyOn(v, 'fetch').mockImplementation(async () => {
    v.items = items
  })
  const sessions = useSessionsStore(pinia)
  vi.spyOn(sessions, 'fetch').mockImplementation(async () => {
    sessions.items = [{ id: 's1', name: 'Harbour at dusk' }]
  })
  const toasts = useToastsStore(pinia)
  vi.spyOn(toasts, 'error')
  wrapper = mount(Videos, { global: { plugins: [pinia] }, attachTo: document.body })
  return { v, toasts, pinia }
}
afterEach(() => {
  wrapper?.unmount()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('Videos', () => {
  it('lists videos with metadata', async () => {
    setup()
    await flushPromises()
    const t = wrapper.text()
    expect(t).toContain('Harbour at dusk')
    expect(t).not.toContain('s1')
    expect(t).toContain('out.mp4')
    expect(t).toContain('1:05')
    expect(t).toContain('24 fps')
    expect(t).toContain('H.264')
  })

  it('shows empty state', async () => {
    setup([])
    await flushPromises()
    expect(wrapper.text()).toContain('No rendered videos')
  })

  it('plays inline in a modal using the plain URL without a key', async () => {
    setup()
    await flushPromises()
    await wrapper.find('[role=listitem] button').trigger('click')
    await flushPromises()
    const video = document.body.querySelector('[data-testid=player]')
    expect(video.getAttribute('src')).toContain('/videos/')
  })

  it('with an API key it uses an object URL and revokes it on unmount', async () => {
    const { pinia } = setup()
    useAuthStore(pinia).apiKey = 'k'
    URL.createObjectURL = vi.fn(() => 'blob:v')
    URL.revokeObjectURL = vi.fn()
    await flushPromises()
    await wrapper.find('[role=listitem] button').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('[data-testid=player]').getAttribute('src')).toBe('blob:v')
    wrapper.unmount()
    wrapper = null
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:v')
  })

  it('delete failure shows a toast; success removes via store', async () => {
    const { v, toasts } = setup()
    vi.spyOn(v, 'remove').mockRejectedValueOnce(new Error('gone'))
    await flushPromises()
    const del = wrapper.findAll('button').find((b) => b.text().includes('Delete'))
    await del.trigger('click')
    await del.trigger('click')
    await flushPromises()
    expect(v.remove).toHaveBeenCalledWith('s1', 'out.mp4')
    expect(toasts.error).toHaveBeenCalled()
  })

  it('without a storage shows the No storage empty state, no request and no error toast', async () => {
    const { v, toasts, pinia } = setup()
    wrapper.unmount()
    v.fetch.mockClear()
    useStorageStore(pinia).loaded = true
    useStorageStore(pinia).targetId = null
    wrapper = mount(Videos, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.find('[data-testid=no-target]').text()).toContain('No storage chosen')
    expect(v.fetch).not.toHaveBeenCalled()
    expect(toasts.error).not.toHaveBeenCalled()
  })

  it('a NO_TARGET refusal shows the same state instead of a toast', async () => {
    const { v, toasts } = setup()
    wrapper.unmount()
    const { pinia } = setup()
    const videos = useVideosStore(pinia)
    videos.fetch.mockRestore?.()
    vi.spyOn(videos, 'fetch').mockRejectedValue(
      Object.assign(new Error('x'), { code: 'NO_TARGET' }),
    )
    wrapper.unmount()
    wrapper = mount(Videos, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.find('[data-testid=no-target]').exists()).toBe(true)
    expect(toasts.error).not.toHaveBeenCalled()
    void v
  })
})
