import { ref } from 'vue'

/**
 * Wrap an async function: tracks loading + error, still rethrows so callers can handle it.
 * const { run, loading, error } = useAsync(() => store.doThing())
 */
export function useAsync(fn) {
  const loading = ref(false)
  const error = ref(null)
  async function run(...args) {
    loading.value = true
    error.value = null
    try {
      return await fn(...args)
    } catch (e) {
      error.value = e
      throw e
    } finally {
      loading.value = false
    }
  }
  return { run, loading, error }
}
