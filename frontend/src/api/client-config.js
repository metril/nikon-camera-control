// Initial config for the generated client (referenced by openapi-ts.config.js).
// Kept dependency-free: the generated client imports it at module load.
export const createClientConfig = (config) => ({
  ...config,
  baseUrl: '',
  throwOnError: true,
  responseStyle: 'data',
})
