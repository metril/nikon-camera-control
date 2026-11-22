import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', async (orig) => {
  const mod = await orig()
  return { ...mod, api: { updateConfig: vi.fn(), resetConfig: vi.fn() } }
})
import { api } from '@/api'
import { useConfigStore } from './config'
import { useAuthStore } from './auth'

describe('config store restart tracking', () => {
  let c
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    c = useConfigStore()
  })

  it('accumulates restart-required fields across config_changed events', () => {
    c.onChanged({ config: {}, restart_required: ['liveview.fps'] })
    c.onChanged({ config: {}, restart_required: [] })
    c.onChanged({ config: {}, restart_required: ['media.dir', 'liveview.fps'] })
    expect(c.restartRequired).toEqual(['liveview.fps', 'media.dir'])
  })

  it('patch accumulates too, and dismiss clears', async () => {
    c.onChanged({ config: {}, restart_required: ['a'] })
    api.updateConfig.mockResolvedValue({ config: {}, restart_required: ['b'] })
    await c.patch({})
    expect(c.restartRequired).toEqual(['a', 'b'])
    c.dismissRestart()
    expect(c.restartRequired).toEqual([])
  })

  it('clears when the server boot identifier (info.started_at) changes', async () => {
    const auth = useAuthStore()
    auth.info = { started_at: 't1' }
    await Promise.resolve()
    c.onChanged({ config: {}, restart_required: ['a'] })
    auth.info = { started_at: 't2' }
    await vi.waitFor(() => expect(c.restartRequired).toEqual([]))
  })

  it('exposes the fields a reset changed when the server reports them', async () => {
    api.resetConfig.mockResolvedValue({ config: {}, restart_required: [], changed: ['video.crf'] })
    await c.reset()
    expect(c.resetChanged).toEqual(['video.crf'])
  })
})
