import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api', () => ({
  api: {
    getAuthStatus: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    pairKiosk: vi.fn(),
    setPassword: vi.fn(),
    deletePassword: vi.fn(),
    getInfo: vi.fn(),
  },
}))
import { api } from '@/api'
import { takePairCode, useAuthStore } from './auth'

const st = (o = {}) => ({
  auth_required: true,
  password_set: true,
  api_key_set: false,
  authenticated: true,
  session_kind: 'browser',
  ...o,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  localStorage.clear()
  history.replaceState(null, '', '/')
})

describe('auth store', () => {
  it('requires sign-in only when the server is protected and this browser is not signed in', () => {
    const a = useAuthStore()
    a.applyStatus(st({ authenticated: false }))
    expect(a.required).toBe(true)
    a.applyStatus(st())
    expect(a.required).toBe(false)
    a.applyStatus(st({ auth_required: false, password_set: false, authenticated: true }))
    expect(a.required).toBe(false)
  })

  it('picks the banner: open, key-only, or none', () => {
    const a = useAuthStore()
    expect(a.banner).toBe(null)
    a.applyStatus(st({ auth_required: false, password_set: false }))
    expect(a.banner).toBe('open')
    a.applyStatus(st({ password_set: false, api_key_set: true }))
    expect(a.banner).toBe('key-only')
    a.applyStatus(st())
    expect(a.banner).toBe(null)
  })

  it('login stores the status and bumps the epoch so sockets reconnect', async () => {
    const a = useAuthStore()
    api.login.mockResolvedValue(st())
    await a.login({ password: 'x' })
    expect(api.login).toHaveBeenCalledWith({ body: { password: 'x' } })
    expect(a.status.authenticated).toBe(true)
    expect(a.epoch).toBe(1)
  })

  it('a 401 settles through the status: open again means no sign-in', async () => {
    const a = useAuthStore()
    api.getAuthStatus.mockResolvedValue(st({ auth_required: false, password_set: false }))
    a.markRequired()
    expect(a.required).toBe(true)
    await vi.waitFor(() => expect(a.required).toBe(false))
  })

  it('signOut calls logout and then requires sign-in', async () => {
    const a = useAuthStore()
    a.applyStatus(st())
    api.logout.mockResolvedValue({ ok: true })
    api.getAuthStatus.mockResolvedValue(st({ authenticated: false }))
    await a.signOut()
    expect(api.logout).toHaveBeenCalled()
    expect(a.required).toBe(true)
    expect(a.canSignOut).toBe(false)
  })

  it('setPassword sends current only when given and flags the change', async () => {
    const a = useAuthStore()
    api.setPassword.mockImplementation(async () => {
      expect(a.changing).toBe(true)
      return st()
    })
    await a.setPassword({ current: '', next: 'new-pass' })
    expect(api.setPassword).toHaveBeenCalledWith({ body: { current: null, new: 'new-pass' } })
    expect(a.changing).toBe(false)
    expect(a.status.password_set).toBe(true)
  })

  it('removePassword needs the current password and returns to open mode', async () => {
    const a = useAuthStore()
    api.deletePassword.mockResolvedValue(
      st({ auth_required: false, password_set: false, authenticated: true }),
    )
    await a.removePassword('old')
    expect(api.deletePassword).toHaveBeenCalledWith({ body: { current: 'old' } })
    expect(a.banner).toBe('open')
  })

  it('swaps a legacy localStorage key for a session once, then deletes it', async () => {
    const a = useAuthStore()
    localStorage.setItem('nikon-api-key', 'old')
    api.login.mockResolvedValue(st({ password_set: false, api_key_set: true }))
    await a.migrateLegacyKey()
    expect(api.login).toHaveBeenCalledWith({ body: { api_key: 'old' } })
    expect(localStorage.getItem('nikon-api-key')).toBe(null)
    api.login.mockClear()
    await a.migrateLegacyKey()
    expect(api.login).not.toHaveBeenCalled()
  })

  it('deletes a stale legacy key even when the swap fails', async () => {
    const a = useAuthStore()
    localStorage.setItem('nikon-api-key', 'old')
    api.login.mockRejectedValue(new Error('no'))
    await a.migrateLegacyKey()
    expect(localStorage.getItem('nikon-api-key')).toBe(null)
  })
})

describe('takePairCode', () => {
  it('reads #pair=<code> and swaps the hash for #/shoot without a new history entry', () => {
    history.replaceState(null, '', '/?layout=touch&kiosk=1#pair=abc%2B123')
    const before = history.length
    expect(takePairCode()).toBe('abc+123')
    expect(location.hash).toBe('#/shoot')
    expect(location.search).toBe('?layout=touch&kiosk=1')
    expect(history.length).toBe(before)
  })
  it('returns nothing and leaves other hashes alone', () => {
    history.replaceState(null, '', '/#/gallery')
    expect(takePairCode()).toBe('')
    expect(location.hash).toBe('#/gallery')
  })
  it('pairs with the code and keeps the server message when it fails', async () => {
    const a = useAuthStore()
    api.pairKiosk.mockResolvedValue(st({ session_kind: 'kiosk' }))
    await a.pairKiosk('c1')
    expect(api.pairKiosk).toHaveBeenCalledWith({ body: { code: 'c1' } })
    expect(a.epoch).toBe(1)
    api.pairKiosk.mockRejectedValue(new Error('That pairing code has expired.'))
    await expect(a.pairKiosk('c2')).rejects.toThrow()
    expect(a.pairError).toBe('That pairing code has expired.')
  })
})
