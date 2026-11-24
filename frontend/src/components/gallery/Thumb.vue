<script setup>
defineOptions({ name: 'GalleryThumb' })
import { ref, watch, onMounted, onUnmounted } from 'vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { useFilesStore } from '@/stores/files'

const props = defineProps({
  path: { type: String, required: true },
  size: { type: Number, default: 256 },
  supported: { type: Boolean, default: true },
  alt: { type: String, default: '' },
  eager: { type: Boolean, default: false },
  /** cover (grid tiles, filmstrip) or contain (previews) */
  fit: { type: String, default: 'cover' },
})
const files = useFilesStore()
const root = ref(null)
const src = ref(null)
const failed = ref(false)
const visible = ref(props.eager)
let observer = null
let gen = 0
let release = () => {}

function drop() {
  release()
  release = () => {}
}

async function load() {
  if (!visible.value || !props.supported) return
  const mine = ++gen
  failed.value = false
  src.value = null
  drop()
  try {
    const h = await files.acquireThumbnail(props.path, props.size)
    if (mine !== gen) return h.release()
    release = h.release
    src.value = h.url
  } catch {
    if (mine === gen) failed.value = true
  }
}

onMounted(() => {
  if (visible.value) return load()
  if (typeof IntersectionObserver === 'undefined') {
    visible.value = true
    return load()
  }
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        visible.value = true
        observer?.disconnect()
        observer = null
        load()
      }
    },
    { rootMargin: '200px' },
  )
  observer.observe(root.value)
})
onUnmounted(() => {
  gen++
  observer?.disconnect()
  drop()
})
watch(() => [props.path, props.size], load)
</script>

<template>
  <div ref="root" class="flex h-full w-full items-center justify-center bg-black">
    <img
      v-if="src && !failed"
      :src="src"
      :alt="alt"
      class="block h-full w-full"
      :class="fit === 'contain' ? 'object-contain' : 'object-cover'"
      draggable="false"
      @error="failed = true"
    />
    <span
      v-else-if="!supported || failed"
      data-testid="thumb-placeholder"
      class="inline-flex text-camera-faint"
      role="img"
      aria-label="No preview available"
    >
      <UiIcon name="ImageOff" :size="24" />
    </span>
    <span
      v-else
      class="h-full w-full animate-pulse bg-camera-raised"
      data-testid="thumb-skeleton"
    />
  </div>
</template>
