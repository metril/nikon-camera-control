<script setup>
/** The newest saved photos. A strip under the live view, or a 2-column grid in the side column. */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import UiButton from '@/components/ui/UiButton.vue'

const emit = defineEmits(['open-gallery'])
const camera = useCameraStore()
const capture = useCaptureStore()
const files = useFilesStore()

const thumbs = ref({}) // path -> src
const releases = []
let gone = false
onUnmounted(() => {
  gone = true
  releases.splice(0).forEach((r) => r())
})

watch(
  () => capture.recent,
  (list) => {
    for (const f of list) {
      if (thumbs.value[f.path]) continue
      files
        .acquireThumbnail(f.path, 200)
        .then((h) => {
          if (gone) return h.release()
          releases.push(h.release)
          thumbs.value = { ...thumbs.value, [f.path]: h.url }
        })
        .catch(() => {})
    }
  },
  { immediate: true },
)
onMounted(() => capture.loadRecent().catch(() => {}))
watch(
  () => camera.connected,
  (on) => on && capture.loadRecent().catch(() => {}),
)
const newest = (i) =>
  i === 0 && capture.lastCapture?.files?.some((f) => f.path === capture.recent[0]?.path)
</script>

<template>
  <div class="film" data-testid="recent-captures">
    <div class="flex items-center justify-between gap-2">
      <span class="eyebrow">Recent captures</span>
      <UiButton variant="ghost" size="sm" class="-mr-2.5" @click="emit('open-gallery')">
        Open Gallery
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
:global(html[data-layout='touch']) .thumb {
  width: 150px;
}
/* Desktop, 1200px and wider: a 2-column grid that fills the side column under the shutter. */
@media (min-width: 1200px) {
  :global(html[data-layout='desktop']) .filmrow {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    overflow-x: hidden;
    overflow-y: auto;
    max-height: 100%;
    align-content: start;
  }
  :global(html[data-layout='desktop']) .thumb {
    width: auto;
  }
}
</style>
