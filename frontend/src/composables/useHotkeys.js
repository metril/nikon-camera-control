import { onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'

const IGNORED = 'input, select, textarea, button, [contenteditable=""], [contenteditable="true"]'

/** The on-screen keyboard is up: typing belongs to the field, never to app hotkeys. */
export const oskOpen = () => document.documentElement.hasAttribute('data-osk-open')

export function isTypingTarget(el) {
  return !!(el && el.closest && el.closest(IGNORED))
}

/** Real text entry only (buttons are not): Ctrl+A and Esc must still work after a button click. */
export function isTextTarget(el) {
  return !!(el && el.closest && el.closest('input, textarea, select, [contenteditable]'))
}

/**
 * Bind a document keydown handler while the component is shown. Under KeepAlive a hidden view
 * stays mounted, so it unbinds on deactivate and rebinds on activate.
 */
export function useDocumentKeydown(handler) {
  const listen = () => document.addEventListener('keydown', handler)
  const unlisten = () => document.removeEventListener('keydown', handler)
  onMounted(listen)
  onActivated(listen)
  onDeactivated(unlisten)
  onBeforeUnmount(unlisten)
}

/**
 * useHotkeys({ ' ': handler, 'c': handler }) - keys match event.key (case-insensitive).
 * Ignores events from inputs, selects, textareas, buttons and contenteditable, and modified keys.
 */
export function useHotkeys(map) {
  const keys = Object.fromEntries(Object.entries(map).map(([k, v]) => [k.toLowerCase(), v]))
  function onKeydown(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return
    if (isTypingTarget(e.target) || oskOpen()) return
    const fn = keys[String(e.key).toLowerCase()]
    if (!fn) return
    e.preventDefault()
    fn(e)
  }
  useDocumentKeydown(onKeydown)
  return { onKeydown }
}
