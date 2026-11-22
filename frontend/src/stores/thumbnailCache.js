/**
 * Reference-counted LRU of object URLs. An entry's URL is revoked only when it has been
 * evicted/replaced/cleared AND no holder still has it acquired.
 */
export class BlobUrlLru {
  constructor(max = 200, revoke = (u) => URL.revokeObjectURL(u)) {
    this.max = max
    this.revoke = revoke
    this.map = new Map() // key -> entry (insertion order = recency)
  }
  has(key) {
    return this.map.has(key)
  }
  /** Take a reference to the cached URL for `key`; call release() when no longer displayed. */
  acquire(key) {
    const entry = this.map.get(key)
    if (!entry) return undefined
    this.map.delete(key)
    this.map.set(key, entry)
    entry.refs++
    let done = false
    return {
      url: entry.url,
      release: () => {
        if (done) return
        done = true
        entry.refs--
        this._maybeRevoke(entry)
      },
    }
  }
  /** Insert a fresh URL (unreferenced until acquired). */
  set(key, url) {
    const old = this.map.get(key)
    if (old) this._drop(old)
    this.map.delete(key)
    this.map.set(key, { url, refs: 0, dropped: false })
    while (this.map.size > this.max) {
      const [k, e] = this.map.entries().next().value
      this.map.delete(k)
      this._drop(e)
    }
  }
  clear() {
    for (const e of this.map.values()) this._drop(e)
    this.map.clear()
  }
  _drop(entry) {
    entry.dropped = true
    this._maybeRevoke(entry)
  }
  _maybeRevoke(entry) {
    if (entry.dropped && entry.refs <= 0 && !entry.revoked) {
      entry.revoked = true
      this.revoke(entry.url)
    }
  }
}
