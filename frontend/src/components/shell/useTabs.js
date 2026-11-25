import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

export const TABS = [
  { id: 'shoot', label: 'Shoot', icon: 'Camera' },
  { id: 'timelapse', label: 'Time-lapse', icon: 'Clock' },
  { id: 'gallery', label: 'Gallery', icon: 'Images' },
  { id: 'settings', label: 'Settings', icon: 'Settings' },
]
const STORAGE_KEY = 'nikon-active-tab'
const valid = (id) => TABS.some((t) => t.id === id)

/** Query part of the hash (`#/settings?section=storage`), shared so views can follow deep links. */
function parseQuery() {
  const q = location.hash.split('?')[1]
  return q ? Object.fromEntries(new URLSearchParams(q)) : {}
}
export const routeQuery = ref(parseQuery())

function fromHash() {
  const id = location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]
  return valid(id) ? id : null
}
function fromStorage() {
  try {
    const id = localStorage.getItem(STORAGE_KEY)
    return valid(id) ? id : null
  } catch {
    return null
  }
}

/** Active tab kept in the URL hash (#/shoot) and remembered across reloads. No router needed. */
export function useTabs() {
  const activeTab = ref(fromHash() || fromStorage() || 'shoot')
  routeQuery.value = parseQuery()

  /** Switch tab; `query` becomes the deep link (`select('settings', { section: 'storage' })`). */
  function select(id, query) {
    if (!valid(id)) return
    if (query && typeof query === 'object' && Object.keys(query).length) {
      location.hash = `#/${id}?${new URLSearchParams(query)}`
      routeQuery.value = { ...query }
    } else if (id !== activeTab.value) routeQuery.value = {}
    activeTab.value = id
  }
  const onHash = () => {
    const id = fromHash()
    if (id) activeTab.value = id
    routeQuery.value = parseQuery()
  }

  watch(
    activeTab,
    (id) => {
      if (fromHash() !== id) location.hash = `#/${id}`
      try {
        localStorage.setItem(STORAGE_KEY, id)
      } catch {
        /* storage unavailable */
      }
    },
    { immediate: true },
  )
  onMounted(() => window.addEventListener('hashchange', onHash))
  onBeforeUnmount(() => window.removeEventListener('hashchange', onHash))
  return { activeTab, select }
}
