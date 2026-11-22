/** Run an async action: record failures in `lastError` (a ref) and always rethrow. */
export async function guard(lastError, fn) {
  try {
    const result = await fn()
    lastError.value = null
    return result
  } catch (e) {
    lastError.value = e
    throw e
  }
}
