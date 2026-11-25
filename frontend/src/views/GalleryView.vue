<script setup>
import { ref, watch } from 'vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import LocalFiles from '@/components/gallery/LocalFiles.vue'
import CameraFiles from '@/components/gallery/CameraFiles.vue'
import Videos from '@/components/gallery/Videos.vue'
import { routeQuery } from '@/components/shell/useTabs'
import { useCameraStore } from '@/stores/camera'
import { useStorageStore } from '@/stores/storage'

const TABS = [
  { value: 'local', label: 'On this server' },
  { value: 'camera', label: 'On the camera card' },
  { value: 'videos', label: 'Time-lapse videos' },
]
const camera = useCameraStore()
const storage = useStorageStore()
const tab = ref('local')
let chosen = false
const pick = (v) => {
  chosen = true
  tab.value = v
}
// Without a storage the server has nothing to show: open on the camera card instead
// (until the user picks a tab themselves).
watch(
  () => [storage.noTarget, camera.connected],
  ([none, on]) => {
    if (!chosen && none && on) tab.value = 'camera'
  },
  { immediate: true },
)

// Deep link: #/gallery?open=<file path> opens that file in the viewer.
const openPath = ref(routeQuery.value.open || '')
watch(
  () => routeQuery.value.open,
  (p) => {
    openPath.value = p || ''
    if (p) pick('local')
  },
)
if (openPath.value) pick('local')
</script>

<template>
  <section class="space-y-4">
    <UiSegmented
      :model-value="tab"
      :options="TABS"
      aria-label="Gallery source"
      class="w-full sm:w-auto"
      @update:model-value="pick"
    />
    <LocalFiles v-if="tab === 'local'" :open-path="openPath" />
    <CameraFiles v-else-if="tab === 'camera'" />
    <Videos v-else />
  </section>
</template>
