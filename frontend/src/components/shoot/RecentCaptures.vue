<script setup>
/** The newest saved photos. A strip under the live view, or a 2-column grid in the side column. */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import { useStorageStore } from '@/stores/storage'
import UiButton from '@/components/ui/UiButton.vue'

const emit = defineEmits(['open-gallery'])
const camera = useCameraStore()
const capture = useCaptureStore()
const files = useFilesStore()

const thumbs = ref({}) // path -> src
const releases = new Map() // path -> release
const pending = new Set() // paths being fetched
const root = ref(null)
const shown = ref(typeof IntersectionObserver !== 'function') // false while display:none (touch landscape): no fetches
let gone = false
let io = null
onMounted(() => {
  if (typeof IntersectionObserver !== 'function') return
  io = new IntersectionObserver(([e]) => (shown.value = e.isIntersecting))
  io.observe(root.value)
})
onUnmounted(() => {
  gone = true
  io?.disconnect()
  releases.forEach((r) => r())
  releases.clear()
})

watch(
  () => [capture.recent, shown.value],
  ([list, on]) => {
    // free the blob URLs of captures that left the strip
    const keep = new Set(list.map((f) => f.path))
    const next = { ...thumbs.value }
    for (const [path, release] of releases)
      if (!keep.has(path)) {
        release()
        releases.delete(path)
        delete next[path]
      }
    thumbs.value = next
    if (!on) return
    for (const f of list) {
      if (thumbs.value[f.path] || pending.has(f.path)) continue
      pending.add(f.path)
      files
        .acquireThumbnail(f.path, 200)
        .then((h) => {
          pending.delete(f.path)
          if (gone || !capture.recent.some((r) => r.path === f.path)) return h.release()
          releases.set(f.path, h.release)
          thumbs.value = { ...thumbs.value, [f.path]: h.url }
        })
        .catch(() => pending.delete(f.path))
    }
  },
  { immediate: true },
)
onMounted(() => capture.loadRecent().catch(() => {}))
const storage = useStorageStore()
watch(
  () => storage.targetId,
  (id) => id && capture.loadRecent().catch(() => {}),
)
watch(
  () => camera.connected,
  (on) => on && capture.loadRecent().catch(() => {}),
)
const newest = (i) =>
  i === 0 && capture.lastCapture?.files?.some((f) => f.path === capture.recent[0]?.path)
</script>

<template>
  <div ref="root" class="film" data-testid="recent-captures">
    <div class="flex items-center justify-between gap-2">
      <span class="eyebrow">Recent captures</span>
      <UiButton variant="ghost" size="sm" class="-mr-2.5" @click="emit('open-gallery')">
        Open gallery
      </UiButton>
    </div>
    <div v-if="capture.recent.length" class="filmrow">
      <button
        v-for="(f, i) in capture.recent"
        :key="f.path"
        type="button"
        class="thumb"
        :class="{ new: newest(i) }"
        :aria-label="`Open ${f.name} in Gallery`"
        @click="emit('open-gallery', f)"
      >
        <img v-if="thumbs[f.path]" :src="thumbs[f.path]" alt="" />
      </button>
    </div>
    <p v-else class="text-sm text-camera-muted">Captures appear here.</p>
  </div>
</template>

<style scoped>
.film {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.filmrow {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.thumb {
  position: relative;
  flex: none;
  width: 132px;
  aspect-ratio: 3 / 2;
  padding: 0;
  overflow: hidden;
  border-radius: theme('borderRadius.control');
  border: 1px solid theme('colors.camera.subtle');
  background: theme('colors.camera.surface');
  cursor: pointer;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.thumb:hover {
  border-color: theme('colors.camera.border');
}
.thumb:active {
  transform: scale(0.985);
}
.thumb.new {
  outline: 2px solid theme('colors.camera.accent');
  outline-offset: -2px;
}
html[data-layout='touch'] .thumb {
  width: 150px;
}
/* Desktop, 1200px and wider: a 2-column grid that fills the side column under the shutter. */
@media (min-width: 1200px) {
  html[data-layout='desktop'] .filmrow {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    overflow-x: hidden;
    overflow-y: auto;
    max-height: 100%;
    align-content: start;
  }
  html[data-layout='desktop'] .thumb {
    width: auto;
  }
}
</style>
