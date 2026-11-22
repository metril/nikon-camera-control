import { describe, it, expect, vi } from 'vitest'
import { BlobUrlLru } from './thumbnailCache'

describe('BlobUrlLru', () => {
  it('revokes an evicted unreferenced URL', () => {
    const revoke = vi.fn()
    const c = new BlobUrlLru(2, revoke)
    c.set('a', 'blob:a')
    c.set('b', 'blob:b')
    c.acquire('a').release() // a is now most recent
    c.set('c', 'blob:c')
    expect(revoke).toHaveBeenCalledTimes(1)
    expect(revoke).toHaveBeenCalledWith('blob:b')
    expect(c.acquire('b')).toBeUndefined()
  })
  it('defers revocation of an evicted entry until its last release', () => {
    const revoke = vi.fn()
    const c = new BlobUrlLru(1, revoke)
    c.set('a', 'blob:a')
    const h1 = c.acquire('a')
    const h2 = c.acquire('a')
    c.set('b', 'blob:b') // evicts a while held
    expect(revoke).not.toHaveBeenCalled()
    h1.release()
    h1.release() // idempotent
    expect(revoke).not.toHaveBeenCalled()
    h2.release()
    expect(revoke).toHaveBeenCalledWith('blob:a')
    expect(revoke).toHaveBeenCalledTimes(1)
  })
  it('clear() keeps held URLs alive until released and revokes the rest', () => {
    const revoke = vi.fn()
    const c = new BlobUrlLru(5, revoke)
    c.set('a', 'blob:a')
    c.set('b', 'blob:b')
    const h = c.acquire('a')
    c.clear()
    expect(revoke).toHaveBeenCalledTimes(1)
    expect(revoke).toHaveBeenCalledWith('blob:b')
    h.release()
    expect(revoke).toHaveBeenCalledWith('blob:a')
  })
  it('replacing a held URL revokes the old one after release', () => {
    const revoke = vi.fn()
    const c = new BlobUrlLru(5, revoke)
    c.set('a', 'blob:1')
    const h = c.acquire('a')
    c.set('a', 'blob:2')
    expect(revoke).not.toHaveBeenCalled()
    h.release()
    expect(revoke).toHaveBeenCalledWith('blob:1')
  })
})
