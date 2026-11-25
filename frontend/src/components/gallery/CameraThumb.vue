<script setup>
defineOptions({ name: 'CameraThumb' })
import { ref, watch, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { acquireCameraThumb, cancelCameraThumb } from './cameraThumbs'

const props = defineProps({
  folder: { type: String, required: true },
  name: { type: String, required: true },
  supported: { type: Boolean, default: true },
})
const root = ref(null)
const src = ref(null)
const failed = ref(false)
const visible = ref(false)
let observer = null
let gen = 0
let release = () => {}
let queued = null // [folder, name] while a fetch of ours may still be waiting

const dequeue = () => {
  if (queued) cancelCameraThumb(...queued)
  queued = null
}

async function load() {
  if (!visible.value || !props.supported) return
  dequeue()
  const mine = ++gen
  failed.value = false
  src.value = null
  release()
  release = () => {}
  queued = [props.folder, props.name]
  try {
    const h = await acquireCameraThumb(props.folder, props.name)
    if (mine !== gen) return h.release()
    queued = null
    release = h.release
    src.value = h.url
  } catch {
    if (mine === gen) failed.value = true
  }
}
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') {
    visible.value = true
    return load()
  }
  observer = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return
      visible.value = true
      observer?.disconnect()
      observer = null
      load()
    },
    { rootMargin: '100px' },
  )
  observer.observe(root.value)
})
// Hidden by KeepAlive: stop queueing USB requests that would delay the shutter or live view.
onDeactivated(() => {
  gen++
  dequeue()
})
onActivated(() => {
  if (visible.value && !src.value && !failed.value) load()
})
onUnmounted(() => {
  gen++
  dequeue()
  observer?.disconnect()
  release()
})
watch(() => [props.folder, props.name], load)
</script>

<template>
  <div
    ref="root"
    class="flex h-full w-full items-center justify-center overflow-hidden rounded-control bg-black"
    data-testid="card-thumb"
  >
    <img
      v-if="src && !failed"
      :src="src"
      alt=""
      class="block h-full w-full object-cover"
      draggable="false"
      @error="failed = true"
    />
    <UiIcon v-else-if="!supported || failed" name="ImageOff" :size="20" class="text-camera-faint" />
    <span v-else class="h-full w-full animate-pulse bg-camera-raised" />
  </div>
</template>
