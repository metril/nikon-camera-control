import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

const STORAGE_KEY = 'nikon-api-key'

function readKey() {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}
function writeKey(key) {
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* storage unavailable: key lives for this session only */
  }
}

export const useAuthStore = defineStore('auth', () => {
  const apiKey = ref(readKey())
  /** True after a 401 / ws 4401: the UI should prompt for the key. */
  const required = ref(false)
  /** True while this browser is creating/rotating the key: sockets closed with 4401 just reconnect. */
  const keyChanging = ref(false)
  const authEnabled = ref(null)
  const info = ref(null)
  const lastError = ref(null)

  function setKey(key) {
    apiKey.value = (key || '').trim()
    writeKey(apiKey.value)
    required.value = false
  }
  function clearKey() {
    apiKey.value = ''
    writeKey('')
  }
  function markRequired() {
    required.value = true
  }

  async function fetchInfo() {
    return guard(lastError, async () => {
      info.value = await api.getInfo()
      authEnabled.value = info.value.auth_enabled
      if (!authEnabled.value) required.value = false
      return info.value
    })
  }

  return {
    apiKey,
    required,
    keyChanging,
    authEnabled,
    info,
    lastError,
    setKey,
    clearKey,
    markRequired,
    fetchInfo,
  }
})
