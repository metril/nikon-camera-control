import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'
import { useAuthStore } from './auth'

export const useConfigStore = defineStore('config', () => {
  const config = ref(null) // ConfigOut
  const schema = ref(null) // JSON schema for the editable config
  const restartRequired = ref([])
  const lastError = ref(null)

  const apply = (out) => {
    config.value = out.config
    restartRequired.value = out.restart_required || []
    return out
  }

  const fetch = () => guard(lastError, async () => (config.value = await api.getConfig()))
  const fetchSchema = () =>
    guard(lastError, async () => (schema.value = (await api.getConfigSchema()).json_schema))
  /** body: ConfigPatch (partial sections). */
  const patch = (body) => guard(lastError, async () => apply(await api.updateConfig({ body })))
  const reset = () => guard(lastError, async () => apply(await api.resetConfig()))

  /** Generate or rotate the key. Returns the plaintext key (shown once) and stores it for this browser. */
  async function createApiKey() {
    const out = await guard(lastError, () => api.createApiKey())
    config.value = out.config
    const auth = useAuthStore()
    auth.setKey(out.api_key)
    auth.authEnabled = true
    return out.api_key
  }
  async function deleteApiKey() {
    await guard(lastError, () => api.deleteApiKey())
    useAuthStore().clearKey()
    useAuthStore().authEnabled = false
    if (config.value) config.value = { ...config.value, api_key_set: false }
  }

  const onChanged = ({ config: c, restart_required }) => {
    if (c) config.value = c
    restartRequired.value = restart_required || []
  }

  return {
    config,
    schema,
    restartRequired,
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
