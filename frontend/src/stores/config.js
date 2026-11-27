import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'
import { useAuthStore } from './auth'

export const useConfigStore = defineStore('config', () => {
  const config = ref(null) // ConfigOut
  const schema = ref(null) // JSON schema for the editable config
  /** Fields whose change needs an app restart; accumulated until the server restarts or dismissed. */
  const restartRequired = ref([])
  /** Fields changed by the last reset-to-defaults (when the server reports them). */
  const resetChanged = ref(null)
  const lastError = ref(null)

  const addRestart = (fields) => {
    if (fields?.length) restartRequired.value = [...new Set([...restartRequired.value, ...fields])]
  }
  const dismissRestart = () => (restartRequired.value = [])
  const apply = (out) => {
    config.value = out.config
    addRestart(out.restart_required)
    return out
  }

  // A new server boot identifier (GET /info `started_at`, when exposed) means the restart happened.
  watch(
    () => useAuthStore().info?.started_at,
    (now, before) => {
      if (before && now && now !== before) dismissRestart()
    },
  )

  const fetch = () => guard(lastError, async () => (config.value = await api.getConfig()))
  const fetchSchema = () =>
    guard(lastError, async () => (schema.value = (await api.getConfigSchema()).json_schema))
  /** body: ConfigPatch (partial sections). */
  const patch = (body) => guard(lastError, async () => apply(await api.updateConfig({ body })))
  const reset = () =>
    guard(lastError, async () => {
      const out = apply(await api.resetConfig())
      resetChanged.value = Array.isArray(out.changed) ? out.changed : null
      return out
    })

  /**
   * Generate or rotate the API key (for scripts). Returns the plaintext key, shown once. Changing
   * it closes every socket with 4401, so this browser re-reads its session afterwards.
   */
  async function createApiKey() {
    const auth = useAuthStore()
    auth.changing = true
    try {
      const out = await guard(lastError, () => api.createApiKey())
      config.value = out.config
      // Without a password the key is the only credential: sign this browser in with it.
      if (!auth.status?.password_set) await auth.login({ api_key: out.api_key }).catch(() => {})
      else await auth.fetchStatus().catch(() => {})
      return out.api_key
    } finally {
      auth.changing = false
      auth.epoch++
    }
  }
  async function deleteApiKey() {
    const auth = useAuthStore()
    auth.changing = true
    try {
      await guard(lastError, () => api.deleteApiKey())
      if (config.value) config.value = { ...config.value, api_key_set: false }
      await auth.fetchStatus().catch(() => {})
    } finally {
      auth.changing = false
      auth.epoch++
    }
  }

  const onChanged = ({ config: c, restart_required }) => {
    if (c) config.value = c
    addRestart(restart_required)
  }

  return {
    config,
    schema,
    restartRequired,
    resetChanged,
    dismissRestart,
    lastError,
    fetch,
    fetchSchema,
    patch,
    reset,
    createApiKey,
    deleteApiKey,
    onChanged,
  }
})
