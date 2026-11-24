import { computed, ref } from 'vue'

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
const coarse = () => {
  try {
    return !!window.matchMedia?.('(pointer: coarse)').matches
  } catch {
    return false
  }
}

const pref = ref(read())

/** Layout preference (auto | desktop | touch) and the layout in effect, mirrored on <html data-layout>. */
export function useLayoutMode() {
  const layout = computed(() =>
    pref.value === 'auto' ? (coarse() ? 'touch' : 'desktop') : pref.value,
  )
  function apply() {
    document.documentElement.dataset.layout = layout.value
  }
  function setPref(v) {
    if (!PREFS.includes(v)) return
    pref.value = v
    try {
      localStorage.setItem(KEY, v)
    } catch {
      /* storage unavailable: the preference lasts for this session */
    }
    apply()
  }
  apply()
  return { pref, layout, setPref }
}
