import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { getCameraPreview: vi.fn(), getCameraThumbnail: vi.fn() },
}))
import { api } from '@/api'
import {
  acquireCameraPreview,
  prefetchCameraPreview,
  keepCameraPreviews,
  cancelCameraPreviews,
  clearCameraPreviews,
  previewKey,
  loadCameraViewerItem,
} from './cameraPreviews'

let pending = []
beforeEach(async () => {
  cancelCameraPreviews()
  for (let i = 0; i < 4; i++) {
    // let reads left by the previous test answer, freeing the single slot
    pending.splice(0).forEach((p) => p.done())
    await new Promise((r) => setTimeout(r, 0))
  }
  clearCameraPreviews()
  pending = []
  URL.createObjectURL = vi.fn(() => 'blob:p')
  URL.revokeObjectURL = vi.fn()
  api.getCameraPreview.mockReset()
  api.getCameraPreview.mockImplementation(
    ({ query, signal }) =>
      new Promise((resolve, reject) => {
        signal?.addEventListener('abort', () => reject(new DOMException('x', 'AbortError')))
        pending.push({ name: query.name, done: () => resolve(new Blob(['x'])) })
      }),
  )
})

describe('cameraPreviews', () => {
  it('reads one file at a time and runs the viewed file before queued prefetches', async () => {
    prefetchCameraPreview('/d', 'a')
    prefetchCameraPreview('/d', 'b')
    const cur = acquireCameraPreview('/d', 'c')
    expect(api.getCameraPreview).toHaveBeenCalledTimes(1) // a started; b and c wait
    pending[0].done()
    await vi.waitFor(() => expect(api.getCameraPreview).toHaveBeenCalledTimes(2))
    expect(pending[1].name).toBe('c') // viewed file jumped ahead of prefetch b
    pending[1].done()
    const h = await cur
    expect(h.url).toBe('blob:p')
  })

  it('cancel aborts running and queued prefetches', async () => {
    prefetchCameraPreview('/d', 'a')
    prefetchCameraPreview('/d', 'b')
    cancelCameraPreviews()
    await Promise.resolve()
    expect(api.getCameraPreview).toHaveBeenCalledTimes(1)
    expect(pending.length).toBe(1)
    pending[0].done()
    await Promise.resolve()
    expect(api.getCameraPreview).toHaveBeenCalledTimes(1) // b never started
  })

  it('keep() aborts files outside the current and adjacent set', async () => {
    const far = acquireCameraPreview('/d', 'far').catch((e) => e.name)
    keepCameraPreviews([previewKey('/d', 'near')])
    expect(await far).toBe('AbortError')
  })

  it('keeps its single slot until the server answers, even for an abandoned file', async () => {
    const a = acquireCameraPreview('/d', 'a').catch((e) => e.name)
    keepCameraPreviews([]) // swiped away from a
    expect(await a).toBe('AbortError')
    const b = acquireCameraPreview('/d', 'b')
    await Promise.resolve()
    expect(api.getCameraPreview).toHaveBeenCalledTimes(1) // a's read is still on the camera
    pending[0].done()
    await vi.waitFor(() => expect(api.getCameraPreview).toHaveBeenCalledTimes(2))
    pending[1].done()
    await b
  })

  it('queues only the newest wanted file behind an in-flight read', async () => {
    const a = acquireCameraPreview('/d', 'a').catch(() => {})
    for (const n of ['b', 'c', 'd']) {
      keepCameraPreviews([previewKey('/d', n)]) // each swipe drops the stale queued ones
      acquireCameraPreview('/d', n).catch(() => {})
    }
    pending[0].done()
    await a
    await vi.waitFor(() => expect(api.getCameraPreview).toHaveBeenCalledTimes(2))
    expect(pending.map((p) => p.name)).toEqual(['a', 'd'])
  })

  it('sends size and mtime as cache busters and keys the cache by them', async () => {
    const p = acquireCameraPreview('/d', 'a', 10, 5)
    expect(api.getCameraPreview.mock.calls[0][0].query).toEqual({
      folder: '/d',
      name: 'a',
      size: 10,
      mtime: 5,
    })
    pending[0].done()
    ;(await p).release()
    const again = acquireCameraPreview('/d', 'a', 11, 5) // same name, other photo
    expect(api.getCameraPreview).toHaveBeenCalledTimes(2)
    pending[1].done()
    await again
  })

  it('clearCameraPreviews forgets cached previews', async () => {
    const p = acquireCameraPreview('/d', 'a', 1, 1)
    pending[0].done()
    ;(await p).release()
    clearCameraPreviews()
    const q = acquireCameraPreview('/d', 'a', 1, 1)
    expect(api.getCameraPreview).toHaveBeenCalledTimes(2)
    pending[1].done()
    await q
  })

  it('shows the thumbnail and the camera message when the preview is refused', async () => {
    api.getCameraThumbnail.mockResolvedValue(new Blob(['t']))
    api.getCameraPreview.mockReset()
    api.getCameraPreview.mockRejectedValue(new Error('Camera is busy (timelapse)'))
    const out = await loadCameraViewerItem(
      { kind: 'image', folder: '/d', name: 'z', size: 1, modified: 2 },
      { placeholder: () => {} },
    )
    expect(out.note).toBe('Camera is busy (timelapse)')
    expect(out.url).toBeTruthy()
  })
})
