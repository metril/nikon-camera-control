import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { api, ApiError } from '@/api'
import { useAuthStore } from '@/stores/auth'

const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })

describe('api client', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('returns data directly on success and sends X-API-Key when set', async () => {
    useAuthStore().setKey('secret')
    fetch.mockResolvedValue(json({ state: 'idle', connected: true }))
    const out = await api.getCamera()
    expect(out.state).toBe('idle')
    const req = fetch.mock.calls[0][0]
    expect(req.headers.get('X-API-Key')).toBe('secret')
    expect(new URL(req.url).pathname).toBe('/api/v1/camera')
  })

  it('omits X-API-Key when no key is set', async () => {
    fetch.mockResolvedValue(json({}))
    await api.getCamera()
    expect(fetch.mock.calls[0][0].headers.has('X-API-Key')).toBe(false)
  })

  it('unwraps the error envelope into ApiError', async () => {
    fetch.mockResolvedValue(
      json(
        { error: { code: 'CAMERA_BUSY', message: 'busy', details: { a: 1 }, request_id: 'r1' } },
        409,
      ),
    )
    const err = await api.getCamera().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err).toMatchObject({
      code: 'CAMERA_BUSY',
      message: 'busy',
      status: 409,
      details: { a: 1 },
      requestId: 'r1',
    })
  })

  it('401 flips the auth store to key-required', async () => {
    const auth = useAuthStore()
    fetch.mockResolvedValue(
      json({ error: { code: 'UNAUTHORIZED', message: 'no', request_id: null } }, 401),
    )
    const err = await api.getCamera().catch((e) => e)
    expect(err.code).toBe('UNAUTHORIZED')
    expect(auth.required).toBe(true)
  })

  it('network failure becomes ApiError NETWORK', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    const err = await api.getCamera().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe('NETWORK')
    expect(err.status).toBe(0)
  })

  it('non-envelope error bodies still give an ApiError', async () => {
    fetch.mockResolvedValue(new Response('Bad gateway', { status: 502 }))
    const err = await api.getCamera().catch((e) => e)
    expect(err).toMatchObject({ code: 'HTTP_ERROR', status: 502 })
  })
})
