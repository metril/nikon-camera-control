import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'

const api = vi.hoisted(() => ({
  listAuthSessions: vi.fn(),
  revokeAuthSession: vi.fn(),
  revokeAllAuthSessions: vi.fn(),
  rotateKioskToken: vi.fn(),
}))
vi.mock('@/api', async (orig) => ({ ...(await orig()), api }))
import SecuritySection from './SecuritySection.vue'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'

const status = (o = {}) => ({
  auth_required: true,
  password_set: true,
  api_key_set: false,
  authenticated: true,
  ...o,
})
const sessions = [
  { id: 'a', kind: 'browser', current: true, created: 't', last_seen: 't', user_agent: 'Firefox' },
  { id: 'b', kind: 'kiosk', current: false, created: 't', last_seen: 't', user_agent: null },
]

async function setup(s = status()) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const auth = useAuthStore()
  auth.status = s
  useConfigStore().config = { api_key_set: !!s.api_key_set }
  api.listAuthSessions.mockResolvedValue({ sessions })
  const w = mount(SecuritySection, { global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return { w, auth }
}
const typeIn = (w, test, value) => w.find(`[data-test="${test}"] input`).setValue(value)

describe('SecuritySection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sets a first password without asking for a current one', async () => {
    const { w, auth } = await setup(
      status({ auth_required: false, password_set: false, authenticated: true }),
    )
    expect(w.find('[data-test="current"]').exists()).toBe(false)
    expect(w.find('[data-test="remove-password"]').exists()).toBe(false)
    auth.setPassword = vi.fn(async () => {})
    await typeIn(w, 'new', 'secret-pass')
    await typeIn(w, 'confirm', 'other')
    expect(w.find('[data-test="mismatch"]').exists()).toBe(true)
    expect(w.find('[data-test="save-password"]').attributes('disabled')).toBeDefined()
    await typeIn(w, 'confirm', 'secret-pass')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(auth.setPassword).toHaveBeenCalledWith({ current: '', next: 'secret-pass' })
  })

  it('states the password rule up front and blocks shorter passwords', async () => {
    const { w } = await setup(
      status({ auth_required: false, password_set: false, authenticated: true }),
    )
    expect(w.find('[data-test="pw-hint"]').text()).toContain('At least 8 characters')
    await typeIn(w, 'new', 'short')
    await typeIn(w, 'confirm', 'short')
    expect(w.find('[data-test="save-password"]').attributes('disabled')).toBeDefined()
    await typeIn(w, 'new', 'longenough')
    await typeIn(w, 'confirm', 'longenough')
    expect(w.find('[data-test="save-password"]').attributes('disabled')).toBeUndefined()
  })

  it('changing needs the current password and shows the server error verbatim', async () => {
    const { w, auth } = await setup()
    auth.setPassword = vi.fn(async () => {
      throw new Error('The current password is wrong.')
    })
    await typeIn(w, 'current', 'nope')
    await typeIn(w, 'new', 'new-pass')
    await typeIn(w, 'confirm', 'new-pass')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="pw-error"]').text()).toBe('The current password is wrong.')
  })

  it('removing the password sends the current one after confirmation', async () => {
    const { w, auth } = await setup()
    auth.removePassword = vi.fn(async () => {})
    const btn = w.find('[data-test="remove-password"]')
    expect(btn.attributes('disabled')).toBeDefined() // no current password typed yet
    await typeIn(w, 'current', 'old-pass')
    await btn.trigger('click')
    await btn.trigger('click') // confirm
    await flushPromises()
    expect(auth.removePassword).toHaveBeenCalledWith('old-pass')
  })

  it('lists sessions, revokes another one, and signs out the others', async () => {
    const { w } = await setup()
    expect(w.findAll('[data-session]')).toHaveLength(2)
    expect(w.find('[data-session="a"]').text()).toContain('This session')
    expect(w.find('[data-session="a"] [data-test="revoke"]').exists()).toBe(false)
    api.revokeAuthSession.mockResolvedValue({ revoked: 1 })
    await w.find('[data-session="b"] [data-test="revoke"]').trigger('click')
    await flushPromises()
    expect(api.revokeAuthSession).toHaveBeenCalledWith({ path: { session_id: 'b' } })
    api.revokeAllAuthSessions.mockResolvedValue({ revoked: 1 })
    const all = w.find('[data-test="revoke-all"]')
    await all.trigger('click')
    await all.trigger('click')
    await flushPromises()
    expect(api.revokeAllAuthSessions).toHaveBeenCalled()
  })

  it('rotates the kiosk token after confirmation', async () => {
    const { w } = await setup()
    api.rotateKioskToken.mockResolvedValue({ revoked: 1 })
    const b = w.find('[data-test="rotate-kiosk"]')
    await b.trigger('click')
    expect(api.rotateKioskToken).not.toHaveBeenCalled()
    await b.trigger('click')
    await flushPromises()
    expect(api.rotateKioskToken).toHaveBeenCalled()
  })

  it('hides the session list while the app is open', async () => {
    const { w } = await setup(
      status({ auth_required: false, password_set: false, authenticated: true }),
    )
    expect(w.find('[data-test="sessions"]').exists()).toBe(false)
    expect(api.listAuthSessions).not.toHaveBeenCalled()
  })
})
