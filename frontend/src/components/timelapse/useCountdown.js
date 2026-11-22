import { ref, onMounted, onUnmounted } from 'vue'

/** `now` (ms) ticking every second while mounted and the tab is visible. */
export function useNow() {
  const now = ref(Date.now())
  let timer = null
  const stop = () => {
    clearInterval(timer)
    timer = null
  }
  const start = () => {
    stop()
    now.value = Date.now()
    timer = setInterval(() => (now.value = Date.now()), 1000)
  }
  const onVis = () => (document.visibilityState === 'hidden' ? stop() : start())
  onMounted(() => {
    start()
    document.addEventListener('visibilitychange', onVis)
  })
  onUnmounted(() => {
    stop()
    document.removeEventListener('visibilitychange', onVis)
  })
  return now
}
