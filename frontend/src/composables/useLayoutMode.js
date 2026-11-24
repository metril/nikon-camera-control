import { computed, effectScope, ref, watchEffect } from 'vue'

const KEY = 'layout'
const PREFS = ['auto', 'desktop', 'touch']

function read() {
  try {
    const v = localStorage.getItem(KEY)
    return PREFS.includes(v) ? v : 'auto'
  } catch {
    return 'auto'
  }
}
function readForced() {
  try {
    const v = new URLSearchParams(location.search).get('layout')
    return v === 'touch' || v === 'desktop' ? v : null
  } catch {
    return null
  }
}

// One shared state: every caller sees (and changes) the same layout.
const pref = ref(read())
const coarse = ref(false)
const forced = ref(readForced())
let installed = false

/** 'touch' or 'desktop': a ?layout= URL parameter wins, then the saved choice, then the pointer. */
const layout = computed(() => {
  if (forced.value) return forced.value
  if (pref.value !== 'auto') return pref.value
  return coarse.value ? 'touch' : 'desktop'
})

function install() {
  if (installed) return
  installed = true
  try {
    const mq = window.matchMedia?.('(pointer: coarse)')
    if (mq) {
      coarse.value = mq.matches
      mq.addEventListener?.('change', (e) => (coarse.value = e.matches))
    }
  } catch {
    /* no media queries: stay on desktop */
  }
  // a detached scope: the attribute stays in sync even if the first caller unmounts
  effectScope(true).run(() =>
    watchEffect(() => {
      document.documentElement.dataset.layout = layout.value
    }),
  )
}

function setPref(v) {
  if (!PREFS.includes(v)) return
  pref.value = v
  try {
    localStorage.setItem(KEY, v)
  } catch {
    /* storage unavailable: the preference lasts for this session */
  }
}

/** Test hook: forget shared state so each test starts clean. */
export function resetLayoutMode() {
  installed = false
  pref.value = read()
  forced.value = readForced()
  coarse.value = false
}

/**
 * Layout mode shared by the whole app, mirrored on <html data-layout>.
 * `pref`: auto | desktop | touch, saved per browser. `forced`: the ?layout= URL value or null
 * (then the choice has no effect). `layout` / `isTouch`: the layout in effect.
 */
export function useLayoutMode() {
  install()
  return { pref, layout, forced, isTouch: computed(() => layout.value === 'touch'), setPref }
}
