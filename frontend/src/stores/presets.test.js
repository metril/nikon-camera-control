import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', async (orig) => {
  const mod = await orig()
  return { ...mod, api: { listPresets: vi.fn() } }
})
import { api } from '@/api'
import { usePresetsStore } from './presets'

describe('presets store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.listPresets.mockResolvedValue({
      items: [
        { id: 's1', kind: 'settings' },
        { id: 'b1', kind: 'bracket' },
      ],
    })
  })

  it('always loads every kind and exposes per-kind lists', async () => {
    const p = usePresetsStore()
    await p.fetch('bracket') // a view asking for one kind must not shrink the shared list
    expect(api.listPresets).toHaveBeenCalledWith({ query: {} })
    expect(p.settingsPresets.map((x) => x.id)).toEqual(['s1'])
    expect(p.bracketPresets.map((x) => x.id)).toEqual(['b1'])
  })
})
