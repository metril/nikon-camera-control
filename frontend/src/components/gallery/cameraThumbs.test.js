import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: { getCameraThumbnail: vi.fn() } }))
import { api } from '@/api'
import { acquireCameraThumb, cancelCameraThumb } from './cameraThumbs'

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:t')
  URL.revokeObjectURL = vi.fn()
})

describe('cameraThumbs queue', () => {
  it('drops a cancelled waiting fetch without touching the camera', async () => {
    const pending = []
    api.getCameraThumbnail.mockImplementation(
      () => new Promise((resolve) => pending.push(() => resolve(new Blob(['x'])))),
    )
    const a = acquireCameraThumb('f', 'a')
    const b = acquireCameraThumb('f', 'b')
    const c = acquireCameraThumb('f', 'c') // waits: only two run at once
    const cRejected = expect(c).rejects.toThrow()
    expect(api.getCameraThumbnail).toHaveBeenCalledTimes(2)
    cancelCameraThumb('f', 'c')
    await cRejected
    pending.forEach((r) => r())
    await Promise.all([a, b])
    expect(api.getCameraThumbnail).toHaveBeenCalledTimes(2)
  })
})
