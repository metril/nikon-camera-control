import { computed, ref, watchEffect } from 'vue'

const KEY = 'nikon-layout'
const PREFS = ['auto', 'desktop', 'touch']

function readPref() {
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
const preference = ref(readPref())
const coarse = ref(false)
const forced = ref(readForced())
let installed = false

/** 'touch' or 'desktop': a ?layout= URL parameter wins, then the saved choice, then the pointer. */
const layout = computed(() => {
  if (forced.value) return forced.value
  if (preference.value !== 'auto') return preference.value
  return coarse.value ? 'touch' : 'desktop'
})

function install() {
  if (installed) return
  installed = true
  const mq = window.matchMedia?.('(pointer: coarse)')
  if (mq) {
    coarse.value = mq.matches
    mq.addEventListener?.('change', (e) => (coarse.value = e.matches))
  }
  watchEffect(() => {
    document.documentElement.dataset.layout = layout.value
  })
}

function setPreference(value) {
  if (!PREFS.includes(value)) return
  preference.value = value
  try {
    localStorage.setItem(KEY, value)
  } catch {
    /* storage unavailable */
  }
}

/** Test hook: forget shared state so each test starts clean. */
export function resetLayoutMode() {
  installed = false
  preference.value = readPref()
  forced.value = readForced()
  coarse.value = false
}

/**
 * Layout mode shared by the whole app. Sets <html data-layout>.
 * `preference`: auto | desktop | touch (saved per browser). `forced`: the ?layout= value or null,
 * in which case the choice cannot be changed. `layout` / `isTouch`: the layout in effect.
 */
export function useLayoutMode() {
  install()
  return {
    preference,
    layout,
    forced,
    isTouch: computed(() => layout.value === 'touch'),
    setPreference,
  }
}
