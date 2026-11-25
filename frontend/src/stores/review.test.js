import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createTestingPinia } from '@pinia/testing'
import { ApiError } from '@/api'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: {
    setSetting: vi.fn(),
    listJobs: vi.fn(),
    listFiles: vi.fn(),
    listCameraFiles: vi.fn(),
    listCameraFolders: vi.fn(),
    getTimelapseStatus: vi.fn(),
    getBattery: vi.fn(),
  },
}))
import { api } from '@/api'
import { useSettingsStore } from './settings'
import { useToastsStore } from './toasts'
import { useTimelapseStore } from './timelapse'
import { useCaptureStore } from './capture'
import { useEventsStore } from './events'
import { useCameraStore } from './camera'
import { useJobsStore } from './jobs'
import { useFilesStore } from './files'
import { useCameraFilesStore } from './cameraFiles'
import { useLiveViewStore } from './liveview'
import { useCameraAdminStore } from './cameraAdmin'
import { useAuthStore } from './auth'
import { useStorageStore } from './storage'
import { useRecordingStore } from './recording'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((a, b) => ((resolve = a), (reject = b)))
  return { promise, resolve, reject }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('toasts.error', () => {
  it('keeps the ApiError details and applies prefix/suffix', () => {
    const t = useToastsStore()
    const e = new ApiError({
      code: 'BUSY',
      message: 'Camera busy',
      details: { camera_message: 'Out of focus', nikon_manual: 'p. 5' },
      requestId: 'r1',
    })
    t.error(e, { prefix: 'ISO', suffix: ' (reverted)' })
    expect(t.items[0]).toMatchObject({
      message: 'ISO: Camera busy (reverted)',
      code: 'BUSY',
      requestId: 'r1',
      reported: 'Out of focus',
      manual: 'p. 5',
    })
    t.error('plain', { prefix: 'X' })
    expect(t.items[1].message).toBe('X: plain')
  })
})

describe('settings echo handling', () => {
  it('ignores a stale echo of an earlier write, applies a foreign event after the last write', async () => {
    const s = useSettingsStore()
    s.common = [{ name: 'iso', value: 100 }]
    const d1 = deferred()
    const d2 = deferred()
    api.setSetting.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const p1 = s.set('iso', 200)
    const p2 = s.set('iso', 400)
    d1.resolve({ name: 'iso', value: 200 })
    await vi.waitFor(() => expect(api.setSetting).toHaveBeenCalledTimes(2))
    s.onSettingChanged({ name: 'iso', value: 200 }) // late echo of A, after B went out
    d2.resolve({ name: 'iso', value: 400 })
    await Promise.all([p1, p2])
    expect(s.get('iso')).toBe(400)
    // an unrelated camera-side change during the write still wins afterwards
    const d3 = deferred()
    api.setSetting.mockReturnValueOnce(d3.promise)
    const p3 = s.set('iso', 800)
    s.onSettingChanged({ name: 'iso', value: 1600 })
    d3.resolve({ name: 'iso', value: 800 })
    await p3
    expect(s.get('iso')).toBe(1600)
  })
})

describe('timelapse progress', () => {
  it('is cleared on timelapse_started and when the status is applied', async () => {
    const t = useTimelapseStore()
    api.getTimelapseStatus.mockResolvedValue({ state: 'running', counters: {} })
    t.onEvent('timelapse_frame', { frames_done: 5 })
    expect(t.progress.frames_done).toBe(5)
    t.onEvent('timelapse_started', {})
    expect(t.progress).toBeNull()
    t.onEvent('timelapse_frame', { frames_done: 2 })
    await t.fetchStatus()
    expect(t.progress).toBeNull()
  })
})

function quiet(status = { connected: false }) {
  createTestingPinia({ stubActions: false, createSpy: vi.fn })
  vi.spyOn(useCameraStore(), 'fetchStatus').mockResolvedValue(status)
  for (const st of [useJobsStore, useTimelapseStore, useLiveViewStore, useRecordingStore])
    for (const n of ['fetchStatus', 'fetch']) if (st()[n]) vi.spyOn(st(), n).mockResolvedValue({})
  vi.spyOn(useAuthStore(), 'fetchInfo').mockResolvedValue({})
  vi.spyOn(useStorageStore(), 'refresh').mockResolvedValue({})
}

describe('capture flags', () => {
  it('reset on camera_disconnected and on resync', () => {
    quiet()
    const c = useCaptureStore()
    const ev = useEventsStore()
    c.onStarted({ bulb: true })
    ev.dispatch({ type: 'camera_disconnected', data: {} })
    expect([c.inFlight, c.bulbActive]).toEqual([false, false])
    c.onStarted({ bulb: true })
    ev.resync()
    expect([c.inFlight, c.bulbActive]).toEqual([false, false])
  })
})

describe('resync battery', () => {
  it('fetches the battery when the camera is connected', async () => {
    quiet({ connected: true })
    const cam = useCameraStore()
    vi.spyOn(cam, 'fetchBattery').mockResolvedValue({})
    vi.spyOn(useSettingsStore(), 'fetchCommon').mockResolvedValue([])
    vi.spyOn(useCameraAdminStore(), 'refresh').mockResolvedValue({})
    useEventsStore().resync()
    await vi.waitFor(() => expect(cam.fetchBattery).toHaveBeenCalled())
  })
})

describe('jobs.fetch', () => {
  it('keeps a job upserted by an event while the fetch was in flight', async () => {
    const j = useJobsStore()
    const d = deferred()
    api.listJobs.mockReturnValue(d.promise)
    const p = j.fetch()
    j.upsert({ id: 'a', status: 'completed', created: '1' })
    d.resolve([{ id: 'a', status: 'running', created: '1' }])
    await p
    expect(j.byId.a.status).toBe('completed')
  })
})

describe('request sequencing', () => {
  it('files.load drops a stale response', async () => {
    const f = useFilesStore()
    const d1 = deferred()
    api.listFiles
      .mockReturnValueOnce(d1.promise)
      .mockResolvedValueOnce({ items: ['new'], total: 1, folders: [] })
    const p1 = f.load({ page: 1 })
    await f.load({ page: 2 })
    d1.resolve({ items: ['old'], total: 9, folders: [] })
    await p1
    expect(f.items).toEqual(['new'])
    expect(f.loading).toBe(false)
  })
  it('cameraFiles.loadFiles drops a stale response', async () => {
    const f = useCameraFilesStore()
    const d1 = deferred()
    api.listCameraFiles
      .mockReturnValueOnce(d1.promise)
      .mockResolvedValueOnce({ items: ['new'], total: 1 })
    const p1 = f.loadFiles({ folder: '/a' })
    await f.loadFiles({ folder: '/b' })
    d1.resolve({ items: ['old'], total: 9 })
    await p1
    expect(f.items).toEqual(['new'])
  })
})

describe('liveview.onStarted', () => {
  it('works before any status was fetched', () => {
    const lv = useLiveViewStore()
    lv.onStarted()
    expect(lv.running).toBe(true)
  })
})
