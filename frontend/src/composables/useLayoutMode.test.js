import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { effectScope } from 'vue'
import { resetLayoutMode, useLayoutMode } from './useLayoutMode'

function useIn(fn) {
  const scope = effectScope()
  const r = scope.run(fn)
  return { r, stop: () => scope.stop() }
}
let listeners
function fakeMedia(coarse) {
  listeners = []
  vi.stubGlobal('matchMedia', () => ({
    matches: coarse,
    addEventListener: (_t, fn) => listeners.push(fn),
  }))
}

describe('useLayoutMode', () => {
  beforeEach(() => {
    localStorage.clear()
    history.replaceState(null, '', '/')
    delete document.documentElement.dataset.layout
  })
  afterEach(() => vi.unstubAllGlobals())

  it('auto: a coarse pointer means touch, a fine one desktop', async () => {
    fakeMedia(true)
    resetLayoutMode()
    const a = useIn(() => useLayoutMode())
    expect(a.r.layout.value).toBe('touch')
    a.stop()
    fakeMedia(false)
    resetLayoutMode()
    const b = useIn(() => useLayoutMode())
    expect(b.r.layout.value).toBe('desktop')
    b.stop()
  })

  it('the user can override Auto, saved in localStorage, and it sets <html data-layout>', async () => {
    fakeMedia(false)
    resetLayoutMode()
    const { r, stop } = useIn(() => useLayoutMode())
    r.setPref('touch')
    await Promise.resolve()
    expect(localStorage.getItem('layout')).toBe('touch')
    expect(document.documentElement.dataset.layout).toBe('touch')
    r.setPref('auto')
    await Promise.resolve()
    expect(document.documentElement.dataset.layout).toBe('desktop')
    r.setPref('nonsense')
    expect(r.pref.value).toBe('auto')
    stop()
  })

  it('?layout= forces the mode over everything', async () => {
    fakeMedia(false)
    localStorage.setItem('layout', 'desktop')
    history.replaceState(null, '', '/?layout=touch')
    resetLayoutMode()
    const { r, stop } = useIn(() => useLayoutMode())
    expect(r.forced.value).toBe('touch')
    expect(r.layout.value).toBe('touch')
    r.setPref('desktop')
    expect(r.layout.value).toBe('touch')
    stop()
  })

  it('follows the pointer when it changes while on Auto', async () => {
    fakeMedia(false)
    resetLayoutMode()
    const { r, stop } = useIn(() => useLayoutMode())
    expect(r.isTouch.value).toBe(false)
    listeners.forEach((fn) => fn({ matches: true }))
    expect(r.isTouch.value).toBe(true)
    stop()
  })

  it('survives unavailable storage', () => {
    fakeMedia(false)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    resetLayoutMode()
    const { r, stop } = useIn(() => useLayoutMode())
    expect(() => r.setPref('touch')).not.toThrow()
    expect(r.layout.value).toBe('touch')
    stop()
    vi.restoreAllMocks()
  })
})
