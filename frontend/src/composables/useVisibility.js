import { ref, onMounted, onBeforeUnmount } from 'vue'

/** Reactive page visibility; use it to pause polling while the tab is hidden. */
export function useVisibility() {
  const visible = ref(document.visibilityState !== 'hidden')
  const update = () => (visible.value = document.visibilityState !== 'hidden')
  onMounted(() => document.addEventListener('visibilitychange', update))
  onBeforeUnmount(() => document.removeEventListener('visibilitychange', update))
  return visible
}

/** setInterval that skips ticks while hidden and is cleaned up on unmount. */
export function useVisiblePolling(fn, ms) {
  let timer = null
  onMounted(() => {
    timer = setInterval(() => {
      if (document.visibilityState !== 'hidden') fn()
    }, ms)
  })
  onBeforeUnmount(() => clearInterval(timer))
}
