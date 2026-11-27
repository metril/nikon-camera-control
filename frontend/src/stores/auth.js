import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

// Browsers used to keep the API key here; it is traded for a session cookie once, then deleted.
const LEGACY_KEY = 'nikon-api-key'

/**
 * Take the single-use kiosk pairing code from `#pair=<code>`. The hash is replaced in place with
 * the default route (replaceState adds no history entry), so the code never stays in the address
 * bar or in back-history, and the tab router never sees `pair=` as a tab. Returns '' when absent.
 */
export function takePairCode() {
  const m = /(?:^#|&)pair=([^&]*)/.exec(globalThis.location?.hash || '')
  if (!m) return ''
  history.replaceState(null, '', location.pathname + location.search + '#/shoot')
  try {
    return decodeURIComponent(m[1])
  } catch {
    return m[1]
  }
}

export const useAuthStore = defineStore('auth', () => {
  /** GET /auth/status: {auth_required, password_set, api_key_set, authenticated, session_kind}. */
  const status = ref(null)
  /** True after a 401 / ws 4401 while the server wants credentials: show the sign-in screen. */
  const required = ref(false)
  /** True while this browser changes the password or key: sockets closed with 4401 just reconnect. */
  const changing = ref(false)
  /** Bumped whenever this browser's credentials change: sockets reconnect with the new cookie. */
  const epoch = ref(0)
  const info = ref(null)
  const lastError = ref(null)
  /** The server's message when kiosk pairing failed; the sign-in screen shows it. */
  const pairError = ref('')

  /** Which "unprotected" banner applies: 'open' (nothing set), 'key-only' (no password) or null. */
  const banner = computed(() => {
    const s = status.value
    if (!s) return null
    if (!s.auth_required) return 'open'
    return s.password_set ? null : 'key-only'
  })
  const canSignOut = computed(() => !!status.value?.auth_required && !!status.value?.authenticated)

  function applyStatus(s) {
    status.value = s
    required.value = !!s.auth_required && !s.authenticated
    return s
  }
  const fetchStatus = () => guard(lastError, async () => applyStatus(await api.getAuthStatus()))
  /** Adopt a status-shaped response, or re-read the status when the response is something else. */
  async function adopt(out) {
    return out && 'auth_required' in out ? applyStatus(out) : fetchStatus()
  }

  function markRequired() {
    required.value = true
    // The server may be open again (password removed elsewhere): the status settles it.
    fetchStatus().catch(() => {})
  }

  async function login(credentials) {
    const out = await api.login({ body: credentials })
    applyStatus(out)
    epoch.value++
    return out
  }
  /** Trade the single-use code from the kiosk URL for a kiosk session. */
  async function pairKiosk(code) {
    try {
      const out = await api.pairKiosk({ body: { code } })
      pairError.value = ''
      applyStatus(out)
      epoch.value++
      return out
    } catch (e) {
      pairError.value = e?.message || 'Kiosk pairing failed.'
      throw e
    }
  }
  async function signOut() {
    try {
      await api.logout()
    } finally {
      await fetchStatus().catch(() => {})
      epoch.value++
    }
  }

  /** Set (no `current` in open mode) or change the password; this browser stays signed in. */
  async function setPassword({ current, next }) {
    changing.value = true
    try {
      await adopt(await api.setPassword({ body: { current: current || null, new: next } }))
    } finally {
      changing.value = false
      epoch.value++
    }
  }
  /** Remove the password (needs the current one): the app returns to open mode. */
  async function removePassword(current) {
    changing.value = true
    try {
      await adopt(await api.deletePassword({ body: { current } }))
    } finally {
      changing.value = false
      epoch.value++
    }
  }

  /** Swap an API key left in localStorage by an older version for a session, then delete it. */
  async function migrateLegacyKey() {
    let key
    try {
      key = localStorage.getItem(LEGACY_KEY)
    } catch {
      return
    }
    if (!key) return
    if (!status.value?.authenticated) {
      try {
        await login({ api_key: key }) // only accepted while no password is set
      } catch {
        /* a stale key: the sign-in screen takes over */
      }
    }
    try {
      localStorage.removeItem(LEGACY_KEY)
    } catch {
      /* storage unavailable */
    }
  }

  async function fetchInfo() {
    return guard(lastError, async () => (info.value = await api.getInfo()))
  }

  return {
    status,
    required,
    changing,
    epoch,
    info,
    lastError,
    pairError,
    banner,
    canSignOut,
    applyStatus,
    fetchStatus,
    markRequired,
    login,
    pairKiosk,
    signOut,
    setPassword,
    removePassword,
    migrateLegacyKey,
    fetchInfo,
  }
})
