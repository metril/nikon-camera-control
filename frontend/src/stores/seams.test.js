import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: {
    downloadVideo: vi.fn().mockResolvedValue(new Blob(['v'])),
    downloadCameraFile: vi.fn().mockResolvedValue(new Blob(['c'])),
    getCameraDatetime: vi.fn().mockResolvedValue({ camera_time: 'x' }),
    getCaptureTarget: vi.fn().mockResolvedValue({ value: 'a', choices: ['a', 'b'] }),
    setCaptureTarget: vi.fn().mockResolvedValue({ value: 'b', choices: ['a', 'b'] }),
  },
  downloadBlob: vi.fn(),
}))
import { api, downloadBlob } from '@/api'
import { useVideosStore } from './videos'
import { useCameraFilesStore } from './cameraFiles'
import { useToastsStore } from './toasts'
import { useCameraAdminStore } from './cameraAdmin'
import { ApiError } from '@/api'

beforeEach(() => {
  setActivePinia(createPinia())
  URL.createObjectURL = vi.fn(() => 'blob:v')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.clearAllMocks())

describe('videos.acquire', () => {
  it('returns the plain URL: the session cookie authenticates it', async () => {
    const r = await useVideosStore().acquire('s1', 'a b.mp4')
    expect(r.url).toBe('/api/v1/videos/s1/a%20b.mp4')
    expect(api.downloadVideo).not.toHaveBeenCalled()
  })
})

describe('cameraFiles.download', () => {
  it('fetches a blob (header auth) and saves it', async () => {
    await useCameraFilesStore().download('/store/DCIM/100', 'a.jpg')
    expect(api.downloadCameraFile).toHaveBeenCalledWith({
      path: { folder: '/store/DCIM/100', name: 'a.jpg' },
      parseAs: 'blob',
    })
    expect(downloadBlob).toHaveBeenCalled()
  })
})

describe('toasts', () => {
  it('keeps ApiError code/status/requestId and never auto-dismisses errors', () => {
    vi.useFakeTimers()
    const t = useToastsStore()
    t.error(new ApiError({ code: 'BUSY', message: 'm', status: 409, requestId: 'r1' }))
    t.info('hi')
    vi.advanceTimersByTime(60_000)
    expect(t.items).toHaveLength(1)
    expect(t.items[0]).toMatchObject({ code: 'BUSY', status: 409, requestId: 'r1', kind: 'error' })
    vi.useRealTimers()
  })
})

describe('cameraAdmin', () => {
  it('refresh loads the clock and capture target; setTarget stores the answer', async () => {
    const s = useCameraAdminStore()
    await s.refresh()
    expect(s.clock.data.camera_time).toBe('x')
    await s.setTarget('b')
    expect(s.target.value).toBe('b')
  })
})
