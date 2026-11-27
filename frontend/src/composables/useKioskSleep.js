import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api'
import { useConfigStore } from '@/stores/config'

/** True only for the kiosk browser: its URL carries kiosk=1 (set by the kiosk entrypoint). */
export function isKioskPage() {
  try {
    return new URLSearchParams(location.search).get('kiosk') === '1'
  } catch {
    return false
  }
}

/** How long after the release the overlay stays, to absorb the click that follows the waking tap. */
const RELEASE_GUARD_MS = 400
const ACTIVITY = ['pointerdown', 'keydown', 'wheel']

/**
 * Kiosk screen sleep. Does nothing unless the page has kiosk=1. After kiosk.sleep_after_min
 * minutes without pointer, key or wheel input, `asleep` turns on (the overlay covers the page)
 * and the display state "off" is posted. The waking tap is swallowed by the overlay.
 */
export function useKioskSleep() {
  const kiosk = isKioskPage()
  const config = useConfigStore()
  const asleep = ref(false)
  const awake = ref(false) // woken, overlay only absorbing the rest of the touch
  let timer = null
  let guard = null
  let pressed = false

  const minutes = computed(() => {
    const n = Number(config.config?.kiosk?.sleep_after_min)
    return Number.isFinite(n) && n > 0 ? n : 0 // 0 or not loaded yet: never sleep
  })
  const post = (on) => {
    try {
      Promise.resolve(api.setKioskDisplay({ body: { on } })).catch(() => {})
    } catch {
      /* the screen state is best effort */
    }
  }
  const clear = () => {
    clearTimeout(timer)
    timer = null
  }
  function arm() {
    clear()
    if (!kiosk || (asleep.value && !awake.value) || !minutes.value) return
    timer = setTimeout(sleep, minutes.value * 60_000)
  }
  function sleep() {
    timer = null
    awake.value = false
    asleep.value = true
    post(false)
  }
  /** Wake from the overlay: post on, restart the timer, drop the overlay once the touch is released. */
  function wake() {
    post(true)
    pressed = true
    awake.value = true // the overlay stays until the touch is released
    arm()
  }

  function release() {
    if (!pressed) return
    pressed = false
    clearTimeout(guard)
    guard = setTimeout(() => {
      asleep.value = false
      awake.value = false
    }, RELEASE_GUARD_MS)
  }
  function onActivity() {
    if (!asleep.value || awake.value) arm()
  }
  /** Overlay pointerdown. */
  function onOverlayDown(e) {
    e.preventDefault()
    e.stopPropagation()
    if (!awake.value) wake()
  }
  function swallow(e) {
    e.preventDefault()
    e.stopPropagation()
  }

  watch(minutes, (m) => {
    if (!kiosk) return
    if (!m && asleep.value && !awake.value) {
      asleep.value = false // sleep switched off while asleep
      awake.value = false
      post(true)
    }
    arm()
  })

  onMounted(() => {
    if (!kiosk) return
    if (!config.config) config.fetch?.()
    for (const t of ACTIVITY)
      window.addEventListener(t, onActivity, { capture: true, passive: true })
    window.addEventListener('pointerup', release, true)
    window.addEventListener('pointercancel', release, true)
    arm()
  })
  onBeforeUnmount(() => {
    clear()
    clearTimeout(guard)
    for (const t of ACTIVITY) window.removeEventListener(t, onActivity, true)
    window.removeEventListener('pointerup', release, true)
    window.removeEventListener('pointercancel', release, true)
  })

  return { kiosk, asleep, onOverlayDown, swallow }
}
