import { describe, it, expect, vi } from 'vitest'
import { BlobUrlLru } from './thumbnailCache'

describe('BlobUrlLru', () => {
  it('revokes the least recently used URL when over capacity', () => {
    const revoke = vi.fn()
    const c = new BlobUrlLru(2, revoke)
    c.set('a', 'blob:a')
    c.set('b', 'blob:b')
    c.get('a') // a is now most recent
    c.set('c', 'blob:c')
    expect(revoke).toHaveBeenCalledTimes(1)
    expect(revoke).toHaveBeenCalledWith('blob:b')
    expect(c.get('b')).toBeUndefined()
    expect(c.get('a')).toBe('blob:a')
  })
  it('revokes a replaced URL and everything on clear()', () => {
    const revoke = vi.fn()
    const c = new BlobUrlLru(5, revoke)
    c.set('a', 'blob:1')
    c.set('a', 'blob:2')
    expect(revoke).toHaveBeenCalledWith('blob:1')
    c.set('b', 'blob:3')
    c.clear()
    expect(revoke).toHaveBeenCalledWith('blob:2')
    expect(revoke).toHaveBeenCalledWith('blob:3')
    expect(c.get('a')).toBeUndefined()
  })
})
