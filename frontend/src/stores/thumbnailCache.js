/** LRU of object URLs: revokes the URL of every evicted entry. */
export class BlobUrlLru {
  constructor(max = 200, revoke = (u) => URL.revokeObjectURL(u)) {
    this.max = max
    this.revoke = revoke
    this.map = new Map() // key -> url (insertion order = recency)
  }
  get(key) {
    if (!this.map.has(key)) return undefined
    const url = this.map.get(key)
    this.map.delete(key)
    this.map.set(key, url)
    return url
  }
  set(key, url) {
    const old = this.map.get(key)
    if (old && old !== url) this.revoke(old)
    this.map.delete(key)
    this.map.set(key, url)
    while (this.map.size > this.max) {
      const [k, u] = this.map.entries().next().value
      this.map.delete(k)
      this.revoke(u)
    }
  }
  clear() {
    for (const u of this.map.values()) this.revoke(u)
    this.map.clear()
  }
}
