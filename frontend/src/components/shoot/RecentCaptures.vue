<script setup>
/** The newest saved photos. A strip under the live view, or a 2-column grid in the side column. */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { fileUrl } from '@/api'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import { useStorageStore } from '@/stores/storage'
import UiButton from '@/components/ui/UiButton.vue'

const emit = defineEmits(['open-gallery'])
const camera = useCameraStore()
const capture = useCaptureStore()
const files = useFilesStore()
const { isTouch } = useLayoutMode()
/** How many fit without scrolling: 6 on touch (3 across), 8 on desktop (4 across). */
const limit = computed(() => (isTouch.value ? 6 : 8))
const shownList = computed(() => capture.recent.slice(0, limit.value))

const thumbs = ref({}) // path -> src
const releases = new Map() // path -> release
const pending = new Set() // paths being fetched
const root = ref(null)
const shown = ref(typeof IntersectionObserver !== 'function') // false while not displayed: no fetches
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
  () => [shownList.value, shown.value],
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
          if (gone || !shownList.value.some((r) => r.path === f.path)) return h.release()
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
const ext = (f) => (f.name?.split('.').pop() || '').toUpperCase()
const badge = (f) => (['JPG', 'JPEG', ''].includes(ext(f)) ? '' : ext(f))
const MIME = { JPG: 'image/jpeg', JPEG: 'image/jpeg', NEF: 'image/x-nikon-nef', MP4: 'video/mp4' }
/** Dragging a thumbnail to the desktop saves the file (Chromium DownloadURL). */
function onDragStart(e, f) {
  const url = new URL(fileUrl(f.path), location.href).href
  e.dataTransfer?.setData(
    'DownloadURL',
    `${MIME[ext(f)] || 'application/octet-stream'}:${f.name}:${url}`,
  )
  e.dataTransfer?.setData('text/uri-list', url)
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'copy'
}
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
    <div v-if="shownList.length" class="filmrow">
      <button
        v-for="(f, i) in shownList"
        :key="f.path"
        type="button"
        class="thumb"
        :class="{ new: newest(i) }"
        :aria-label="`Open ${f.name} in Gallery`"
        :title="f.name"
        :draggable="!isTouch"
        @dragstart="onDragStart($event, f)"
        @click="emit('open-gallery', f)"
      >
        <img v-if="thumbs[f.path]" :src="thumbs[f.path]" alt="" draggable="false" />
        <span v-if="badge(f)" class="ext">{{ badge(f) }}</span>
      </button>
    </div>
    <p v-if="shownList.length && !isTouch" class="hint">
      Drag a thumbnail to your desktop to save it.
    </p>
    <p v-else-if="!shownList.length" class="text-sm text-camera-muted">Captures appear here.</p>
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
.ext {
  position: absolute;
  right: 4px;
  bottom: 4px;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.6);
  font:
    11px ui-monospace,
    Menlo,
    monospace;
  color: theme('colors.camera.text');
}
.hint {
  margin: 0;
  font-size: 12px;
  color: theme('colors.camera.muted');
}
/* Wide landscape (desktop and kiosk): a grid under the shutter, 4 across on desktop (8 shown) and
   3 across on touch (6 shown). Nothing here scrolls: the count is capped to what fits. */
@media (min-width: 900px) and (orientation: landscape) {
  .filmrow {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 6px;
    overflow: hidden;
    padding-bottom: 0;
    align-content: start;
  }
  html[data-layout='touch'] .filmrow {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .thumb,
  html[data-layout='touch'] .thumb {
    width: 100%;
    align-self: start;
  }
}
</style>
