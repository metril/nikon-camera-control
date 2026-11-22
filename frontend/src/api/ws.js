import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const PING_MS = 20_000
const BACKOFF_BASE_MS = 500
const BACKOFF_CAP_MS = 15_000
export const CLOSE_UNAUTHORIZED = 4401

export function backoffDelay(attempt, rand = Math.random) {
  const exp = Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** attempt)
  return Math.round(exp / 2 + (rand() * exp) / 2) // 50-100% jitter, never above the cap
}

function wsUrl(path) {
  const loc = globalThis.location
  const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${loc.host}/api/v1${path}`
}

/**
 * Reconnecting WebSocket. status: connecting | open | closed | unauthorized.
 * close() is final: cancels timers and never reconnects.
 */
function createSocket(path, { onMessage, onBinary, onOpen, binary = false } = {}) {
  const status = ref('closed')
  let ws = null
  let attempt = 0
  let reconnectTimer = null
  let pingTimer = null
  let stopped = true

  function clearTimers() {
    clearTimeout(reconnectTimer)
    clearInterval(pingTimer)
    reconnectTimer = pingTimer = null
  }

  function connect() {
    if (stopped) return
    const auth = useAuthStore()
    const protocols = auth.apiKey ? ['apikey', `apikey.${auth.apiKey}`] : undefined
    status.value = 'connecting'
    const sock = new WebSocket(wsUrl(path), protocols)
    ws = sock
    if (binary) sock.binaryType = 'arraybuffer'

    sock.onopen = () => {
      if (stopped || ws !== sock) return sock.close()
      attempt = 0
      status.value = 'open'
      clearInterval(pingTimer)
      pingTimer = setInterval(() => {
        if (sock.readyState === 1) sock.send(JSON.stringify({ type: 'ping' }))
      }, PING_MS)
      onOpen?.()
    }
    sock.onmessage = (ev) => {
      if (stopped || ws !== sock) return
      if (typeof ev.data !== 'string') return onBinary?.(ev.data)
      let msg
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      if (msg && msg.type === 'pong') return
      onMessage?.(msg)
    }
    sock.onerror = () => {} // onclose always follows
    sock.onclose = (ev) => {
      if (ws !== sock) return
      ws = null
      clearInterval(pingTimer)
      pingTimer = null
      if (stopped) return
      if (ev.code === CLOSE_UNAUTHORIZED) {
        stopped = true
        status.value = 'unauthorized'
        useAuthStore().markRequired()
        return
      }
      status.value = 'connecting'
      reconnectTimer = setTimeout(connect, backoffDelay(attempt++))
    }
  }

  return {
    status,
    start() {
      if (!stopped) return
      stopped = false
      attempt = 0
      connect()
    },
    /** Reconnect now (e.g. after the API key changed). */
    restart() {
      this.close()
      this.start()
    },
    close() {
      stopped = true
      clearTimers()
      const sock = ws
      ws = null
      if (sock) {
        sock.onopen = sock.onmessage = sock.onclose = sock.onerror = null
        try {
          sock.close()
        } catch {
          /* already closed */
        }
      }
      if (status.value !== 'unauthorized') status.value = 'closed'
    },
    send(data) {
      if (ws && ws.readyState === 1) ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    },
  }
}

/** /ws/events: onEvent({type, ts, data}); onOpen fires on every (re)connect. */
export function createEventSocket({ onEvent, onOpen } = {}) {
  return createSocket('/ws/events', { onMessage: onEvent, onOpen })
}

/** /ws/liveview: onFrame(ArrayBuffer) for JPEG frames, onStatus(obj) for JSON status messages. */
export function createLiveViewSocket({ onFrame, onStatus, onOpen } = {}) {
  return createSocket('/ws/liveview', {
    binary: true,
    onBinary: onFrame,
    onMessage: onStatus,
    onOpen,
  })
}
