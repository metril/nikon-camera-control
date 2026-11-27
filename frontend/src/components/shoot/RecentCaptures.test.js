import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { nextTick } from 'vue'
import RecentCaptures from './RecentCaptures.vue'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import { resetLayoutMode } from '@/composables/useLayoutMode'

function setup() {
  const p = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const capture = useCaptureStore()
  capture.loadRecent = vi.fn(async () => [])
  const files = useFilesStore()
  const releases = {}
  files.acquireThumbnail = vi.fn(async (path) => ({
    url: `blob:${path}`,
    release: (releases[path] = vi.fn()),
  }))
  return { p, capture, files, releases }
}

describe('RecentCaptures thumbnails', () => {
  it('releases handles of captures that left the list and on unmount', async () => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const { p, capture, releases } = setup()
    capture.recent = [
      { path: 'a', name: 'a' },
      { path: 'b', name: 'b' },
    ]
    const w = mount(RecentCaptures, { global: { plugins: [p] } })
    await flushPromises()
    capture.recent = [
      { path: 'c', name: 'c' },
      { path: 'b', name: 'b' },
    ]
    await flushPromises()
    expect(releases.a).toHaveBeenCalledTimes(1)
    expect(releases.b).not.toHaveBeenCalled()
    w.unmount()
    expect(releases.b).toHaveBeenCalledTimes(1)
    expect(releases.c).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })

  it('does not fetch while hidden, fetches once shown', async () => {
    const { p, capture, files } = setup()
    let cb
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(f) {
          cb = f
        }
        observe() {}
        disconnect() {}
      },
    )
    capture.recent = [{ path: 'a', name: 'a' }]
    const w = mount(RecentCaptures, { global: { plugins: [p] } })
    cb([{ isIntersecting: false }])
    await nextTick()
    expect(files.acquireThumbnail).not.toHaveBeenCalled()
    cb([{ isIntersecting: true }])
    await flushPromises()
    expect(files.acquireThumbnail).toHaveBeenCalledTimes(1)
    w.unmount()
    vi.unstubAllGlobals()
  })
})

describe('RecentCaptures count and drag', () => {
  const many = (n) =>
    Array.from({ length: n }, (_, i) => ({ path: `d/DSC_${i}.NEF`, name: `DSC_${i}.NEF` }))
  const mountWith = (n) => {
    vi.stubGlobal('IntersectionObserver', undefined)
    const { p, capture } = setup()
    capture.recent = many(n)
    return mount(RecentCaptures, { global: { plugins: [p] } })
  }
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.removeItem('layout')
    resetLayoutMode()
  })

  it('shows 8 on desktop and 6 on touch, plus Open gallery', async () => {
    const w = mountWith(12)
    expect(w.findAll('.thumb')).toHaveLength(8)
    expect(w.text()).toContain('Open gallery')
    w.unmount()
    localStorage.setItem('layout', 'touch')
    resetLayoutMode()
    const t = mountWith(12)
    expect(t.findAll('.thumb')).toHaveLength(6)
    expect(t.findAll('.thumb')[0].attributes('draggable')).toBe('false')
    t.unmount()
  })

  it('dragging a thumbnail carries its download URL', async () => {
    const w = mountWith(2)
    const data = {}
    const dataTransfer = { setData: (k, v) => (data[k] = v), effectAllowed: '' }
    await w.findAll('.thumb')[0].trigger('dragstart', { dataTransfer })
    const [mime, name, ...url] = data.DownloadURL.split(':')
    expect(mime).toBe('image/x-nikon-nef')
    expect(name).toBe('DSC_0.NEF')
    expect(url.join(':')).toMatch(/^https?:\/\/.*\/api\/v1\/files\/d%2FDSC_0\.NEF$/)
    expect(dataTransfer.effectAllowed).toBe('copy')
    w.unmount()
  })
})
