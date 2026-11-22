<script setup>
defineOptions({ name: 'GalleryThumb' })
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useFilesStore } from '@/stores/files'

const props = defineProps({
  path: { type: String, required: true },
  size: { type: Number, default: 256 },
  supported: { type: Boolean, default: true },
  alt: { type: String, default: '' },
  eager: { type: Boolean, default: false },
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
  <div ref="root" class="flex h-full w-full items-center justify-center bg-slate-900">
    <img
      v-if="src && !failed"
      :src="src"
      :alt="alt"
      class="h-full w-full object-contain"
      @error="failed = true"
    />
    <span
      v-else-if="!supported || failed"
      data-testid="thumb-placeholder"
      class="text-2xl text-slate-500"
      role="img"
      aria-label="No preview available"
      >🖼</span
    >
    <span v-else class="h-full w-full animate-pulse bg-slate-800" data-testid="thumb-skeleton" />
  </div>
</template>
