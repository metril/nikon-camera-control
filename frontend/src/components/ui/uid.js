let n = 0
/** Unique DOM id for label/for wiring. */
export const uid = (prefix = 'ui') => `${prefix}-${++n}`
