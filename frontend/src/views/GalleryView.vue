<script setup>
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import LocalFiles from '@/components/gallery/LocalFiles.vue'
import CameraFiles from '@/components/gallery/CameraFiles.vue'
import SourceCards from '@/components/gallery/SourceCards.vue'
import { formatSize } from '@/components/gallery/media'
import { routeQuery } from '@/components/shell/useTabs'
import { useCameraStore } from '@/stores/camera'
import { useStorageStore } from '@/stores/storage'
import { storageName } from '@/labels'

const SOURCE_KEY = 'nikon-gallery-source'
const camera = useCameraStore()
const storage = useStorageStore()

const read = () => {
  try {
    const v = localStorage.getItem(SOURCE_KEY)
    return v === 'camera' || v === 'storage' ? v : null
  } catch {
    return null
  }
}
const tab = ref(read() || 'storage')
let picked = false // an explicit choice this visit; a saved one is only the starting point
const pick = (v) => {
  picked = true
  tab.value = v
  try {
    localStorage.setItem(SOURCE_KEY, v)
  } catch {
    /* remembered per viewer when possible */
  }
}
// Without a storage the server has nothing to show: open on the camera instead
// (until the viewer picks a source themselves). The saved choice is left alone.
const active = computed(() =>
  !picked && storage.noTarget && camera.connected ? 'camera' : tab.value,
)
// The card may have been swapped since the last look: read the camera storage on every show.
let shown = false
const refreshStorage = () => camera.connected && camera.fetchStorage().catch(() => {})
onMounted(() => {
  shown = true
  refreshStorage()
})
onActivated(() => {
  if (shown)
    shown = false // the first activation comes with the mount
  else refreshStorage()
})
watch(
  () => camera.connected,
  (on) => on && camera.fetchStorage().catch(() => {}),
)

const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`
const cameraSub = computed(() => {
  if (!camera.connected) return 'Not connected'
  const cards = camera.storage?.cards || []
  if (!cards.length) return 'Connected'
  const free = cards.reduce((a, c) => a + (c.free_kb || 0), 0)
  return `${plural(cards.length, 'card')} · ${formatSize(free * 1024)} free`
})
const storageSub = computed(() => {
  const t = storage.target
  if (!t) return 'No storage chosen'
  // Whole-drive figures only: file counts follow the open folder, so they'd change as you browse.
  if (!t.mounted) return 'Not mounted'
  if (t.free == null) return 'Ready'
  return t.size
    ? `${formatSize(t.free)} free of ${formatSize(t.size)}`
    : `${formatSize(t.free)} free`
})
const sources = computed(() => [
  { value: 'camera', icon: 'Camera', title: 'Camera', subtitle: cameraSub.value },
  {
    value: 'storage',
    icon: storage.target?.kind === 'smb' ? 'Network' : 'HardDrive',
    title: storageName(storage.target),
    subtitle: storageSub.value,
    action: storage.target ? null : { label: 'Choose…', href: '#/settings?section=storage' },
  },
])

// Deep link: #/gallery?open=<file path> opens that file in the viewer.
const openPath = ref(routeQuery.value.open || '')
watch(
  () => routeQuery.value.open,
  (p) => {
    openPath.value = p || ''
    if (p) pick('storage')
  },
)
if (openPath.value) pick('storage')
</script>

<template>
  <section class="flex h-full min-h-0 flex-col gap-3">
    <SourceCards :model-value="active" :sources="sources" @update:model-value="pick" />
    <LocalFiles v-if="active === 'storage'" :open-path="openPath" />
    <CameraFiles v-else />
  </section>
</template>
