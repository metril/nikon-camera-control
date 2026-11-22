import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { ApiError } from '@/api'

vi.mock('@/api', async (orig) => {
  const mod = await orig()
  return { ...mod, api: { setSetting: vi.fn(), listSettings: vi.fn() } }
})
import { api } from '@/api'
import { useSettingsStore } from './settings'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((a, b) => ((resolve = a), (reject = b)))
  return { promise, resolve, reject }
}

describe('settings write queue', () => {
  let s
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    s = useSettingsStore()
    s.common = [{ name: 'iso', value: 100 }]
  })

  it('updates optimistically', async () => {
    const d = deferred()
    api.setSetting.mockReturnValue(d.promise)
    const p = s.set('iso', 200)
    expect(s.get('iso')).toBe(200)
    d.resolve({ name: 'iso', value: 200 })
    await p
  })

  it('coalesces rapid changes: one in flight, then only the newest', async () => {
    const d1 = deferred()
    const d2 = deferred()
    api.setSetting.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const p1 = s.set('iso', 200)
    const p2 = s.set('iso', 400)
    const p3 = s.set('iso', 800)
    expect(api.setSetting).toHaveBeenCalledTimes(1)
    d1.resolve({ name: 'iso', value: 200 })
    await vi.waitFor(() => expect(api.setSetting).toHaveBeenCalledTimes(2))
    expect(api.setSetting.mock.calls[1][0].body).toEqual({ value: 800 }) // 400 was dropped
    expect(s.get('iso')).toBe(800)
    d2.resolve({ name: 'iso', value: 800 })
    await Promise.all([p1, p2, p3])
    expect(s.get('iso')).toBe(800)
  })

  it('rolls back to the last confirmed value and rejects every waiter on error', async () => {
    api.setSetting.mockRejectedValue(
      new ApiError({ code: 'SETTING_INVALID', message: 'bad', status: 422 }),
    )
    const p1 = s.set('iso', 200)
    const p2 = s.set('iso', 400)
    await expect(p1).rejects.toMatchObject({ code: 'SETTING_INVALID' })
    await expect(p2).rejects.toBeInstanceOf(ApiError)
    expect(s.get('iso')).toBe(100)
    expect(s.lastError.code).toBe('SETTING_INVALID')
  })

  it('a new write after a failure works (queue is cleared)', async () => {
    api.setSetting.mockRejectedValueOnce(new ApiError({ code: 'X', message: 'x' }))
    await expect(s.set('iso', 200)).rejects.toThrow()
    api.setSetting.mockResolvedValueOnce({ name: 'iso', value: 300 })
    await s.set('iso', 300)
    expect(s.get('iso')).toBe(300)
  })

  it('ignores setting_changed for a name with a write in flight, applies otherwise', async () => {
    const d = deferred()
    api.setSetting.mockReturnValue(d.promise)
    const p = s.set('iso', 200)
    s.onSettingChanged({ name: 'iso', value: 999 })
    expect(s.get('iso')).toBe(200)
    d.resolve({ name: 'iso', value: 200 })
    await p
    s.onSettingChanged({ name: 'iso', value: 640 })
    expect(s.get('iso')).toBe(640)
  })
})
