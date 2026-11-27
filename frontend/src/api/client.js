import { client } from './generated/client.gen'
import { toApiError } from './errors'
import { useAuthStore } from '@/stores/auth'

// Same-origin base URL is set in client-config.js (baseUrl '', throwOnError, data-only responses).

// Browsers authenticate with the HttpOnly ncc_session cookie, which fetch sends on its own.
// Runs for every failure (HTTP error, network error). The returned value is what gets thrown.
client.interceptors.error.use((error, response) => {
  const err = toApiError(error, response)
  if (err.status === 401) useAuthStore().markRequired()
  return err
})

export { client }
