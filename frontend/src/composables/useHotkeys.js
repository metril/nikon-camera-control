import { onMounted, onBeforeUnmount } from 'vue'

const IGNORED = 'input, select, textarea, button, [contenteditable=""], [contenteditable="true"]'

/** The on-screen keyboard is up: typing belongs to the field, never to app hotkeys. */
export const oskOpen = () => document.documentElement.hasAttribute('data-osk-open')

export function isTypingTarget(el) {
  return !!(el && el.closest && el.closest(IGNORED))
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
  onMounted(() => document.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
  return { onKeydown }
}
