import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { createEventSocket, createLiveViewSocket } from '@/api'
import { backoffDelay } from './ws'
import { useAuthStore } from '@/stores/auth'

class FakeWS {
  static instances = []
  constructor(url, protocols) {
    this.url = url
    this.protocols = protocols
    this.readyState = 0
    this.sent = []
    FakeWS.instances.push(this)
  }
  send(d) {
    this.sent.push(d)
  }
  close() {
    this.readyState = 3
  }
  open() {
    this.readyState = 1
    this.onopen?.()
  }
  msg(data) {
    this.onmessage?.({ data })
  }
  drop(code = 1006) {
    this.readyState = 3
    this.onclose?.({ code })
  }
}
const last = () => FakeWS.instances.at(-1)

describe('event socket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWS.instances = []
    vi.stubGlobal('WebSocket', FakeWS)
    vi.stubGlobal('fetch', () => new Promise(() => {})) // markRequired() re-reads /auth/status
    setActivePinia(createPinia())
    localStorage.clear()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('connects to /api/v1/ws/events and goes open', () => {
    const s = createEventSocket()
    s.start()
    expect(last().url).toMatch(/^ws:\/\/.*\/api\/v1\/ws\/events$/)
    expect(s.status.value).toBe('connecting')
    last().open()
    expect(s.status.value).toBe('open')
    s.close()
  })

  it('offers no subprotocol: the session cookie authenticates the handshake', () => {
    createEventSocket().start()
    expect(last().protocols).toBeUndefined()
  })

  it('delivers events, ignores pong and bad JSON', () => {
    const onEvent = vi.fn()
    const s = createEventSocket({ onEvent })
    s.start()
    last().open()
    last().msg('{"type":"pong"}')
    last().msg('not json')
    last().msg('{"type":"battery","ts":"t","data":{"level":"50"}}')
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent.mock.calls[0][0].type).toBe('battery')
    s.close()
  })

  it('reconnects with growing backoff, capped at 15s', () => {
    const s = createEventSocket()
    s.start()
    for (let i = 0; i < 12; i++) {
      const n = FakeWS.instances.length
      last().drop()
      expect(s.status.value).toBe('connecting')
      vi.advanceTimersByTime(15_000)
      expect(FakeWS.instances.length).toBe(n + 1)
    }
    expect(backoffDelay(0, () => 1)).toBe(500)
    expect(backoffDelay(3, () => 1)).toBe(4000)
    expect(backoffDelay(50, () => 1)).toBe(15_000)
    expect(backoffDelay(50, () => 0)).toBe(7500)
    s.close()
  })

  it('resets the backoff after a successful open', () => {
    const spy = vi.spyOn(globalThis, 'setTimeout')
    const s = createEventSocket()
    s.start()
    last().drop()
    vi.advanceTimersByTime(15_000)
    last().open()
    last().drop()
    const delays = spy.mock.calls.map((c) => c[1]).filter((d) => d >= 250 && d <= 500)
    expect(delays.length).toBeGreaterThanOrEqual(2) // both first-attempt delays are <= 500ms
    s.close()
  })

  it('does not reconnect after close(), and close() cancels the pending timer', () => {
    const s = createEventSocket()
    s.start()
    last().drop()
    const n = FakeWS.instances.length
    s.close()
    vi.advanceTimersByTime(60_000)
    expect(FakeWS.instances.length).toBe(n)
    expect(s.status.value).toBe('closed')
  })

  it('does not reconnect after an explicit close of an open socket', () => {
    const s = createEventSocket()
    s.start()
    const ws = last()
    ws.open()
    s.close()
    ws.drop(1000)
    vi.advanceTimersByTime(60_000)
    expect(FakeWS.instances.length).toBe(1)
  })

  it('4401 stops reconnecting and flips the auth store', () => {
    const s = createEventSocket()
    s.start()
    last().drop(4401)
    vi.advanceTimersByTime(60_000)
    expect(FakeWS.instances.length).toBe(1)
    expect(s.status.value).toBe('unauthorized')
    expect(useAuthStore().required).toBe(true)
  })

  it('pings every 20s while open and stops after close', () => {
    const s = createEventSocket()
    s.start()
    const ws = last()
    ws.open()
    vi.advanceTimersByTime(20_000)
    expect(ws.sent).toEqual(['{"type":"ping"}'])
    vi.advanceTimersByTime(20_000)
    expect(ws.sent.length).toBe(2)
    s.close()
    vi.advanceTimersByTime(60_000)
    expect(ws.sent.length).toBe(2)
  })

  it('restart() reconnects immediately', () => {
    const s = createEventSocket()
    s.start()
    s.restart()
    expect(FakeWS.instances.length).toBe(2)
    s.close()
  })

  it('live view socket: binary frames and JSON status go to separate callbacks', () => {
    const onFrame = vi.fn()
    const onStatus = vi.fn()
    const s = createLiveViewSocket({ onFrame, onStatus })
    s.start()
    expect(last().url).toMatch(/\/api\/v1\/ws\/liveview$/)
    last().open()
    const buf = new ArrayBuffer(4)
    last().msg(buf)
    last().msg('{"type":"status","running":true}')
    expect(onFrame).toHaveBeenCalledWith(buf)
    expect(onStatus).toHaveBeenCalledWith({ type: 'status', running: true })
    s.close()
  })
})

describe('socket close codes', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWS.instances = []
    vi.stubGlobal('WebSocket', FakeWS)
    vi.stubGlobal('fetch', () => new Promise(() => {})) // markRequired() re-reads /auth/status
    setActivePinia(createPinia())
    localStorage.clear()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('4403 is terminal: no reconnect loop and no sign-in prompt', () => {
    const auth = useAuthStore()
    const s = createEventSocket()
    s.start()
    last().drop(4403)
    expect(s.status.value).toBe('forbidden')
    expect(auth.required).toBe(false)
    vi.advanceTimersByTime(60_000)
    expect(FakeWS.instances).toHaveLength(1)
  })

  it('4401 while this browser changes the password reconnects without prompting', () => {
    const auth = useAuthStore()
    const s = createEventSocket()
    s.start()
    auth.changing = true
    last().drop(4401)
    expect(auth.required).toBe(false)
    auth.changing = false
    vi.advanceTimersByTime(20_000)
    expect(FakeWS.instances).toHaveLength(2)
    s.close()
  })

  it('4401 after this browser signed in since connect reconnects', () => {
    const auth = useAuthStore()
    const s = createLiveViewSocket()
    s.start()
    auth.epoch++
    last().drop(4401)
    expect(auth.required).toBe(false)
    vi.advanceTimersByTime(1)
    expect(FakeWS.instances).toHaveLength(2)
    s.close()
  })

  it('4401 with unchanged credentials asks for the sign-in', () => {
    const auth = useAuthStore()
    const s = createEventSocket()
    s.start()
    last().drop(4401)
    expect(s.status.value).toBe('unauthorized')
    expect(auth.required).toBe(true)
  })
})
