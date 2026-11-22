import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import Videos from './Videos.vue'
import { useVideosStore } from '@/stores/videos'
import { useToastsStore } from '@/stores/toasts'
import { useAuthStore } from '@/stores/auth'

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
    expect(t).toContain('s1')
    expect(t).toContain('out.mp4')
    expect(t).toContain('1:05')
    expect(t).toContain('24 fps')
    expect(t).toContain('libx264')
  })

  it('shows empty state', async () => {
    setup([])
    await flushPromises()
    expect(wrapper.text()).toContain('No rendered videos')
  })

  it('plays inline in a modal using the plain URL without a key', async () => {
    setup()
    await flushPromises()
    await wrapper.find('table button').trigger('click')
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
    await wrapper.find('table button').trigger('click')
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
    const del = wrapper.findAll('button').find((b) => b.text() === 'Delete')
    await del.trigger('click')
    await del.trigger('click')
    await flushPromises()
    expect(v.remove).toHaveBeenCalledWith('s1', 'out.mp4')
    expect(toasts.error).toHaveBeenCalled()
  })
})
