import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia } from '@pinia/testing'
import { useCameraFilesStore } from './cameraFiles'
import { api } from '@/api'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { listCameraFiles: vi.fn(), listCameraFolders: vi.fn() },
}))

describe('cameraFiles store', () => {
  let cf
  beforeEach(() => {
    createTestingPinia({ stubActions: false, createSpy: vi.fn })
    cf = useCameraFilesStore()
    api.listCameraFiles.mockReset()
  })

  it('requests newest first by default and passes the order through', async () => {
    api.listCameraFiles.mockResolvedValue({ items: [], total: 0 })
    await cf.loadFiles()
    expect(api.listCameraFiles.mock.calls[0][0].query.order).toBe('newest')
    await cf.loadFiles({ order: 'name' })
    expect(api.listCameraFiles.mock.calls[1][0].query.order).toBe('name')
  })

  it('tracks listing progress and clears it when the load ends', async () => {
    let resolve
    api.listCameraFiles.mockReturnValue(new Promise((r) => (resolve = r)))
    const p = cf.loadFiles()
    cf.onListing({ folder: '/', recursive: false, count: 7, done: false })
    expect(cf.listing).toEqual({ count: 7, done: false })
    resolve({ items: [], total: 0 })
    await p
    expect(cf.listing).toBeNull()
  })

  it('keeps the camera message verbatim in lastError', async () => {
    api.listCameraFiles.mockRejectedValue(new Error('Could not get folder list'))
    await expect(cf.loadFiles()).rejects.toThrow('Could not get folder list')
    expect(cf.lastError.message).toBe('Could not get folder list')
  })

  it('shows only the progress of the walk it is waiting for', async () => {
    api.listCameraFiles.mockReturnValue(new Promise(() => {}))
    cf.loadFiles({ folder: '/', recursive: true })
    cf.onListing({ folder: '/DCIM', recursive: true, count: 3, done: false })
    cf.onListing({ folder: '/', recursive: false, count: 4, done: false })
    expect(cf.listing).toBeNull()
    cf.onListing({ folder: '/', recursive: true, count: 5, done: false })
    expect(cf.listing).toEqual({ count: 5, done: false })
  })
})
