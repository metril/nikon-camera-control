<script setup>
defineOptions({ name: 'GalleryLightbox' })
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import { useFilesStore } from '@/stores/files'
import { formatSize, formatDate, kindTone, resolveFile } from './media'

const props = defineProps({
  open: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:index', 'delete', 'download'])
const files = useFilesStore()

const item = computed(() => props.items[props.index] || null)
const src = ref(null)
const loading = ref(false)
const failed = ref(false)
let release = () => {}
let gen = 0

function drop() {
  release()
  release = () => {}
  src.value = null
}

async function loadPreview() {
  drop()
  const it = item.value
  if (!props.open || !it) return
  const mine = ++gen
  loading.value = true
  failed.value = false
  try {
    if (it.kind === 'image') {
      const r = await resolveFile(it.path)
      if (mine !== gen) return r.release()
      release = r.release
      src.value = r.url
    } else if (it.has_thumbnail !== false) {
      // json/mp4 etc. have no thumbnail: the server answers 415, so do not ask
      const h = await files.acquireThumbnail(it.path, 1024)
      if (mine !== gen) return h.release()
      release = h.release
      src.value = h.url
    }
  } catch {
    if (mine === gen) failed.value = true
  } finally {
    if (mine === gen) loading.value = false
  }
}

const go = (d) => {
  const n = props.index + d
  if (n >= 0 && n < props.items.length) emit('update:index', n)
}
function onKey(e) {
  if (!props.open) return
  if (e.key === 'ArrowLeft') go(-1)
  else if (e.key === 'ArrowRight') go(1)
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  gen++
  drop()
})
watch(() => [props.open, item.value?.path], loadPreview, { immediate: true })
</script>

<template>
  <UiModal :open="open" :title="item?.name || 'Preview'" @close="emit('close')">
    <div v-if="item" class="space-y-3">
      <div class="flex min-h-[40vh] items-center justify-center rounded bg-slate-900">
        <UiSpinner v-if="loading" />
        <img
          v-else-if="src && !failed"
          :src="src"
          :alt="item.name"
          class="max-h-[65vh] max-w-full object-contain"
          @error="failed = true"
        />
        <p v-else class="p-6 text-sm text-slate-400" data-testid="lightbox-nopreview">
          No preview available
        </p>
      </div>
      <dl class="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-slate-300 sm:grid-cols-4">
        <div>
          <dt class="text-xs text-slate-500">Type</dt>
          <dd>
            <UiBadge :tone="kindTone(item.kind)">{{ item.kind }}</UiBadge>
          </dd>
        </div>
        <div>
          <dt class="text-xs text-slate-500">Size</dt>
          <dd>{{ formatSize(item.size) }}</dd>
        </div>
        <div class="col-span-2">
          <dt class="text-xs text-slate-500">Modified</dt>
          <dd>{{ formatDate(item.modified) }}</dd>
        </div>
        <div class="col-span-2 sm:col-span-4">
          <dt class="text-xs text-slate-500">Path</dt>
          <dd class="break-all font-mono text-xs">{{ item.path }}</dd>
        </div>
      </dl>
    </div>
    <template #footer>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex gap-2">
          <UiButton size="sm" aria-label="Previous file" :disabled="index <= 0" @click="go(-1)">
            ←
          </UiButton>
          <UiButton
            size="sm"
            aria-label="Next file"
            :disabled="index >= items.length - 1"
            @click="go(1)"
          >
            →
          </UiButton>
        </div>
        <div class="flex gap-2">
          <UiButton size="sm" :disabled="!item" @click="emit('download', item)">Download</UiButton>
          <UiConfirmButton
            size="sm"
            variant="danger"
            :loading="busy"
            :disabled="!item"
            @confirm="emit('delete', item)"
          >
            Delete
          </UiConfirmButton>
        </div>
      </div>
    </template>
  </UiModal>
</template>
