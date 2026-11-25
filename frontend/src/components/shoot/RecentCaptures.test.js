import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { nextTick } from 'vue'
import RecentCaptures from './RecentCaptures.vue'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'

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
