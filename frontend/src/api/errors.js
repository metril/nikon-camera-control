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

/** Readable text for pydantic/FastAPI validation errors ([{loc, msg}]); '' when not that shape. */
export function validationText(errors) {
  if (!Array.isArray(errors)) return ''
  return errors
    .map((e) => {
      if (typeof e === 'string') return e
      const field = Array.isArray(e?.loc) ? e.loc.filter((p) => p !== 'body').join('.') : ''
      const msg = String(e?.msg ?? '').replace(/^Value error, /, '')
      return field ? `${field}: ${msg}` : msg
    })
    .filter(Boolean)
    .join('; ')
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
    const detail = env.code === 'VALIDATION_ERROR' ? validationText(env.details?.errors) : ''
    return new ApiError({
      code: env.code || 'HTTP_ERROR',
      message: detail || env.message || response.statusText,
      status: response.status,
      details: env.details ?? null,
      requestId: env.request_id ?? response.headers?.get?.('X-Request-ID') ?? null,
    })
  }
  const raw = error && typeof error === 'object' ? error.detail : null
  return new ApiError({
    code: 'HTTP_ERROR',
    message:
      (typeof raw === 'string' && raw) ||
      validationText(raw) ||
      (typeof error === 'string' && error) ||
      response.statusText ||
      `HTTP ${response.status}`,
    status: response.status,
    requestId: response.headers?.get?.('X-Request-ID') ?? null,
  })
}

/** True when the server refused because no storage target is chosen (HTTP 409 NO_TARGET). */
export const isNoTarget = (e) => e?.code === 'NO_TARGET'
