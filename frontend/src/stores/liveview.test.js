import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useLiveViewStore } from './liveview'

describe('liveview tools', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })
  it('cycles the grid thirds, golden, centre, off and persists tools', () => {
    const s = useLiveViewStore()
    expect(s.tools.grid).toBe('thirds')
    const seen = []
    for (let i = 0; i < 4; i++) {
      s.cycleGrid()
      seen.push(s.tools.grid)
    }
    expect(seen).toEqual(['golden', 'centre', 'off', 'thirds'])
    s.toggleTool('peak')
    setActivePinia(createPinia())
    expect(useLiveViewStore().tools.peak).toBe(true)
  })
  it('ignores corrupt stored tools', () => {
    localStorage.setItem('liveview.tools', '{"grid":"bogus","hist":"x"}')
    const s = useLiveViewStore()
    expect(s.tools.grid).toBe('thirds')
    expect(s.tools.hist).toBe(true)
  })
})
