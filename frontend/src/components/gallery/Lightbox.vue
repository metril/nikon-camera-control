<script setup>
defineOptions({ name: 'GalleryLightbox' })
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'
import Thumb from './Thumb.vue'
import { fileKind } from '@/labels'
import { useFilesStore } from '@/stores/files'
import { formatSize, kindTone, resolveFile } from './media'

const MIN_ZOOM = 1
const MAX_ZOOM = 8
const DOUBLE_ZOOM = 2.5
const SWIPE_PX = 60

const props = defineProps({
  open: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
  index: { type: Number, default: 0 },
  busy: { type: Boolean, default: false },
  /** Source adapter: async (item, { placeholder }) => { url, release, note? } | null. Default: local files. */
  loader: { type: Function, default: null },
  downloadLabel: { type: String, default: 'Download' },
  deleteDisabled: { type: Boolean, default: false },
  deleteTitle: { type: String, default: '' },
  /** Position shown as `offset + index + 1 of total` when the items are a window of a longer list. */
  offset: { type: Number, default: 0 },
  total: { type: Number, default: null },
  showDate: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'update:index', 'delete', 'download'])
const files = useFilesStore()

const root = ref(null)
const closeBtn = ref(null)
const strip = ref(null)
const item = computed(() => props.items[props.index] || null)
const isVideo = computed(() => item.value?.kind === 'video' && !props.loader)
const src = ref(null)
const loading = ref(false)
const failed = ref(false)
const note = ref('')
const placeholder = ref(null)
let releasePlaceholder = () => {}
let release = () => {}
let gen = 0
let opener = null

// Zoom and pan
const zoom = ref(1)
const tx = ref(0)
const ty = ref(0)
const dragging = ref(false)
const imgStyle = computed(() => ({
  transform: `translate(${tx.value}px, ${ty.value}px) scale(${zoom.value})`,
}))
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`)
const clampZoom = (z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))
function resetZoom() {
  zoom.value = 1
  tx.value = 0
  ty.value = 0
}
function setZoom(z) {
  zoom.value = clampZoom(z)
  if (zoom.value === 1) {
    tx.value = 0
    ty.value = 0
  }
}
const onWheel = (e) => setZoom(zoom.value * Math.exp(-e.deltaY * 0.0015))
const onDouble = () => setZoom(zoom.value > 1 ? 1 : DOUBLE_ZOOM)

// Pointer gestures: one finger pans (when zoomed) or swipes (when not), two fingers pinch.
const pointers = new Map()
let pinchStart = null
let swipeFrom = null
const dist = () => {
  const [a, b] = [...pointers.values()]
  return Math.hypot(a.x - b.x, a.y - b.y)
}
function onPointerDown(e) {
  if (isVideo.value) return
  e.currentTarget.setPointerCapture?.(e.pointerId)
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (pointers.size === 2) {
    pinchStart = { d: dist(), z: zoom.value }
    swipeFrom = null
  } else if (pointers.size === 1) {
    swipeFrom = { x: e.clientX, y: e.clientY }
    dragging.value = zoom.value > 1
  }
}
function onPointerMove(e) {
  const p = pointers.get(e.pointerId)
  if (!p) return
  const dx = e.clientX - p.x
  const dy = e.clientY - p.y
  p.x = e.clientX
  p.y = e.clientY
  if (pointers.size === 2 && pinchStart) {
    setZoom(pinchStart.z * (dist() / (pinchStart.d || 1)))
  } else if (zoom.value > 1) {
    tx.value += dx
    ty.value += dy
  }
}
function onPointerUp(e) {
  if (!pointers.has(e.pointerId)) return
  const wasSingle = pointers.size === 1
  pointers.delete(e.pointerId)
  if (pointers.size < 2) pinchStart = null
  dragging.value = false
  if (wasSingle && swipeFrom && zoom.value === 1) {
    const dx = e.clientX - swipeFrom.x
    const dy = e.clientY - swipeFrom.y
    if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1)
  }
  swipeFrom = null
}

function dropPlaceholder() {
  releasePlaceholder()
  releasePlaceholder = () => {}
  placeholder.value = null
}
function drop() {
  release()
  release = () => {}
  src.value = null
  note.value = ''
  dropPlaceholder()
}

async function loadPreview() {
  drop()
  resetZoom()
  const it = item.value
  if (!props.open || !it) return
  const mine = ++gen
  loading.value = true
  failed.value = false
  try {
    if (props.loader) {
      const r = await props.loader(it, {
        // a quick low-resolution stand-in while the real file loads
        placeholder: (h) => {
          if (mine !== gen || !loading.value) return h.release()
          dropPlaceholder()
          releasePlaceholder = h.release
          placeholder.value = h.url
        },
      })
      if (mine !== gen) return r?.release()
      if (r) {
        release = r.release
        src.value = r.url
        note.value = r.note || ''
      }
    } else if (it.kind === 'image' || it.kind === 'video') {
      const r = await resolveFile(it.path)
      if (mine !== gen) return r.release()
      release = r.release
      src.value = r.url
    } else if (it.has_thumbnail !== false) {
      // RAW and other files: the server's rendered thumbnail is the preview
      const h = await files.acquireThumbnail(it.path, 1024)
      if (mine !== gen) return h.release()
      release = h.release
      src.value = h.url
    }
  } catch {
    if (mine === gen) failed.value = true
  } finally {
    if (mine === gen) {
      loading.value = false
      dropPlaceholder()
    }
  }
}

const go = (d) => {
  const n = props.index + d
  if (n >= 0 && n < props.items.length) emit('update:index', n)
}

const FOCUSABLE = 'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
function onKey(e) {
  if (!props.open) return
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
  } else if (e.key === 'ArrowLeft') go(-1)
  else if (e.key === 'ArrowRight') go(1)
  else if (e.key === 'Tab' && root.value) {
    const els = [...root.value.querySelectorAll(FOCUSABLE)]
    if (!els.length) return
    const first = els[0]
    const last = els[els.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    } else if (!root.value.contains(document.activeElement)) {
      e.preventDefault()
      first.focus()
    }
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  gen++
  drop()
})

watch(
  () => props.open,
  async (o) => {
    if (o) {
      opener = document.activeElement
      await nextTick()
      closeBtn.value?.focus()
    } else {
      opener?.focus?.()
      opener = null
    }
  },
  { immediate: true },
)
watch(() => [props.open, item.value?.path], loadPreview, { immediate: true })
// Keep the current filmstrip thumbnail in view
watch(
  () => [props.open, props.index],
  async () => {
    await nextTick()
    strip.value?.querySelector('[aria-current="true"]')?.scrollIntoView?.({
      inline: 'center',
      block: 'nearest',
    })
  },
)

/** Optional exposure data: only fields the API provides are shown. */
const exif = computed(() => {
  const it = item.value
  if (!it) return []
  const ex = it.exif || {}
  const taken = it.modified
    ? new Date(it.modified * 1000).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : null
  return [
    ['Shutter', ex.shutter],
    ['Aperture', ex.aperture],
    ['ISO', ex.iso],
    ['Exposure comp.', ex.exposure_comp],
    ['White balance', ex.white_balance],
    ['Mode', ex.mode],
    ['Size', formatSize(it.size)],
    ['Taken', taken],
    [
      'Date',
      props.showDate && it.modified
        ? new Date(it.modified * 1000).toLocaleDateString([], { dateStyle: 'medium' })
        : null,
    ],
  ].filter(([, v]) => v != null && v !== '' && v !== '-')
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      ref="root"
      role="dialog"
      aria-modal="true"
      :aria-label="item?.name || 'Preview'"
      class="fixed inset-0 z-50 grid grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)_auto_auto] bg-black text-camera-text"
      data-testid="lightbox"
    >
      <div
        class="flex min-w-0 items-center gap-3 bg-camera-bg py-2.5 max-[560px]:gap-1.5 pl-[max(24px,env(safe-area-inset-left,0px))] max-[560px]:pl-[max(8px,env(safe-area-inset-left,0px))] pr-[max(16px,env(safe-area-inset-right,0px))] max-[560px]:pr-[max(8px,env(safe-area-inset-right,0px))] pt-[calc(10px+env(safe-area-inset-top,0px))]"
      >
        <button
          ref="closeBtn"
          type="button"
          aria-label="Close viewer"
          class="inline-flex h-[var(--ctl-sm)] w-[var(--ctl-sm)] flex-none items-center justify-center rounded-control text-camera-muted hover:bg-camera-raised hover:text-camera-text"
          @click="emit('close')"
        >
          <UiIcon name="X" />
        </button>
        <span class="min-w-0 flex-1 truncate font-mono text-sm font-medium" :title="item?.name">{{
          item?.name
        }}</span>
        <UiBadge v-if="item" :tone="kindTone(item.kind)">{{ fileKind(item.kind) }}</UiBadge>
        <slot name="actions" :item="item" />
        <UiButton
          size="sm"
          variant="ghost"
          :disabled="!item"
          :aria-label="loader ? downloadLabel : 'Download file'"
          :title="downloadLabel"
          @click="emit('download', item)"
        >
          <UiIcon name="Download" :size="16" />
          <span class="hidden sm:inline">{{ downloadLabel }}</span>
        </UiButton>
        <UiConfirmButton
          size="sm"
          variant="ghost"
          :loading="busy"
          :disabled="!item || deleteDisabled"
          :title="deleteTitle"
          confirm-text="Delete?"
          @confirm="emit('delete', item)"
        >
          <UiIcon name="Trash2" :size="16" />
          <span class="hidden sm:inline">Delete</span>
        </UiConfirmButton>
        <span
          class="flex-none tabular-nums text-[13px] text-camera-muted"
          data-testid="lightbox-position"
        >
          {{ offset + index + 1 }} of {{ total ?? items.length }}
        </span>
      </div>

      <div
        class="relative grid touch-none select-none place-items-center overflow-hidden"
        data-testid="lightbox-stage"
        @wheel.prevent="onWheel"
        @dblclick="onDouble"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
      >
        <template v-if="loading">
          <img
            v-if="placeholder"
            :src="placeholder"
            :alt="item?.name"
            draggable="false"
            class="max-h-full max-w-full object-contain opacity-70"
            data-testid="lightbox-placeholder"
          />
          <UiSpinner :class="placeholder ? 'absolute' : ''" />
        </template>
        <video
          v-else-if="src && !failed && isVideo"
          :src="src"
          controls
          class="max-h-full max-w-full"
          data-testid="lightbox-video"
        />
        <img
          v-else-if="src && !failed"
          :src="src"
          :alt="item.name"
          draggable="false"
          class="max-h-full max-w-full origin-center object-contain"
          :class="dragging ? '' : 'transition-transform duration-[120ms]'"
          :style="imgStyle"
          @error="failed = true"
        />
        <p v-else class="p-6 text-sm text-camera-muted" data-testid="lightbox-nopreview">
          No preview available
        </p>
        <p
          v-if="note && !loading"
          class="absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 rounded-full border border-camera-border bg-camera-surface/85 px-3 py-1 text-center text-xs text-camera-muted"
          data-testid="lightbox-note"
        >
          {{ note }}
        </p>
        <span
          v-if="zoom !== 1"
          class="absolute left-1/2 top-3 -translate-x-1/2 rounded-full border border-camera-border bg-camera-surface/80 px-2 py-0.5 font-mono text-xs tabular-nums"
          data-testid="lightbox-zoom"
          >{{ zoomLabel }}</span
        >
        <button
          type="button"
          aria-label="Previous photo"
          :disabled="index <= 0"
          class="absolute left-4 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full border border-camera-border bg-camera-surface/75 disabled:opacity-30"
          @pointerdown.stop
          @click="go(-1)"
        >
          <UiIcon name="ChevronLeft" :size="22" />
        </button>
        <button
          type="button"
          aria-label="Next photo"
          :disabled="index >= items.length - 1"
          class="absolute right-4 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full border border-camera-border bg-camera-surface/75 disabled:opacity-30"
          @pointerdown.stop
          @click="go(1)"
        >
          <UiIcon name="ChevronRight" :size="22" />
        </button>
      </div>

      <div
        class="grid max-[560px]:grid-cols-4 min-[561px]:flex min-[561px]:flex-wrap min-[561px]:justify-center border-t border-camera-subtle bg-camera-bg"
        data-testid="lightbox-exif"
      >
        <div
          v-for="[k, v] in exif"
          :key="k"
          class="grid gap-px border-r border-camera-subtle px-4 py-2 text-center last:border-r-0 max-[560px]:px-2 max-[560px]:[&:nth-child(4n)]:border-r-0"
        >
          <span class="eyebrow">{{ k }}</span>
          <b class="font-mono text-sm font-medium tabular-nums">{{ v }}</b>
        </div>
      </div>

      <div
        ref="strip"
        class="flex gap-1.5 overflow-x-auto bg-camera-bg px-[max(16px,env(safe-area-inset-left,0px))] pb-[calc(10px+env(safe-area-inset-bottom,0px))] pt-2 [justify-content:safe_center]"
        data-testid="lightbox-strip"
      >
        <button
          v-for="(f, i) in items"
          :key="f.path"
          type="button"
          :aria-label="`Show ${f.name}`"
          :aria-current="i === index ? 'true' : undefined"
          class="aspect-[3/2] w-[72px] flex-none overflow-hidden rounded-[4px] border-2 p-0"
          :class="
            i === index ? 'border-camera-accent opacity-100' : 'border-transparent opacity-60'
          "
          @click="emit('update:index', i)"
        >
          <slot name="thumb" :item="f">
            <Thumb :path="f.path" :supported="f.has_thumbnail" :size="128" />
          </slot>
        </button>
      </div>
    </div>
  </Teleport>
</template>
