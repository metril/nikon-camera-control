/** Error thrown for every failed API call (HTTP non-2xx or network failure). */
export class ApiError extends Error {
  constructor({ code, message, status = 0, details = null, requestId = null }) {
    super(message || code)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
    this.requestId = requestId
  }
}

/** Build an ApiError from a thrown value / response of the generated client. */
export function toApiError(error, response) {
  if (error instanceof ApiError) return error
  if (error && error.name === 'AbortError') return error
  if (!response) {
    return new ApiError({
      code: 'NETWORK',
      message: 'Cannot reach the server',
      details: { cause: String(error?.message ?? error) },
    })
  }
  const env = error && typeof error === 'object' ? error.error : null
  if (env && typeof env === 'object') {
    return new ApiError({
      code: env.code || 'HTTP_ERROR',
      message: env.message || response.statusText,
      status: response.status,
      details: env.details ?? null,
      requestId: env.request_id ?? response.headers?.get?.('X-Request-ID') ?? null,
    })
  }
  return new ApiError({
    code: 'HTTP_ERROR',
    message:
      (typeof error === 'string' && error) || response.statusText || `HTTP ${response.status}`,
    status: response.status,
    requestId: response.headers?.get?.('X-Request-ID') ?? null,
  })
}
