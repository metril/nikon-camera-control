import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: { capturePhoto: vi.fn() } }))
import { api } from '@/api'
import { useCaptureStore } from './capture'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('capture.reset (resync)', () => {
  it('keeps inFlight while a blocking capture request is pending', async () => {
    let done
    api.capturePhoto.mockReturnValueOnce(new Promise((r) => (done = r)))
    const c = useCaptureStore()
    const p = c.capture()
    c.reset()
    expect(c.inFlight).toBe(true)
    done({ files: [] })
    await p
    expect(c.inFlight).toBe(false)
  })
  it('clears stale event-only state', () => {
    const c = useCaptureStore()
    c.onStarted({ bulb: true })
    c.reset()
    expect(c.inFlight).toBe(false)
    expect(c.bulbActive).toBe(false)
  })
})
