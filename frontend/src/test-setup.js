import { afterEach, beforeEach } from 'vitest'

/**
 * Tests must never touch the network. fetch and WebSocket are replaced by guards that record the
 * attempt and throw; a test that needs them installs its own mock (vi.stubGlobal) which wins.
 */
let violations = []
const guardFetch = (input) => {
  const msg = `real fetch to ${typeof input === 'string' ? input : (input?.url ?? String(input))}`
  violations.push(msg)
  throw new Error(`${msg} in a test: mock @/api or stub fetch`)
}
function GuardWebSocket(url) {
  const msg = `real WebSocket to ${url}`
  violations.push(msg)
  throw new Error(`${msg} in a test: stub WebSocket`)
}
globalThis.fetch = guardFetch
globalThis.WebSocket = GuardWebSocket

beforeEach(() => {
  violations = []
  // a test that restored the globals (vi.unstubAllGlobals) lands back on the guards
  if (globalThis.fetch !== guardFetch && globalThis.fetch?.name === 'fetch')
    globalThis.fetch = guardFetch
})
afterEach(() => {
  const v = violations
  violations = []
  if (v.length) throw new Error(`Test made real network calls: ${v.join(', ')}`)
})
