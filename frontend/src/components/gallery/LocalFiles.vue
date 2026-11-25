<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { useFilesStore } from '@/stores/files'
import { useCaptureStore } from '@/stores/capture'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'
import { isNoTarget } from '@/api'
import { fileKind } from '@/labels'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import Thumb from './Thumb.vue'
import Lightbox from './Lightbox.vue'
import { formatSize, formatDate, kindTone } from './media'

const LONG_PRESS_MS = 480

const props = defineProps({ openPath: { type: String, default: '' } })

const files = useFilesStore()
const capture = useCaptureStore()
const jobs = useJobsStore()
const toasts = useToastsStore()
const storage = useStorageStore()

const SORTS = [
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'name', label: 'Name' },
]
const LIMITS = [24, 50, 100, 200].map((n) => ({ value: n, label: `${n} per page` }))

const mode = ref('all') // all | photos | videos
const selecting = ref(false)
const selected = ref(new Set())
const confirmDelete = ref(false)
const lightboxIndex = ref(-1)
// A deep-linked file that is not on the current page is shown on its own.
const linked = ref(null)
const lightboxItems = computed(() => (linked.value ? [linked.value] : shown.value))
const deleting = ref(false)
const failedLoad = ref(false)
const noTarget = computed(
  () => storage.noTarget || (failedLoad.value && isNoTarget(files.lastError)),
)

const q = computed(() => files.query)
const pages = computed(() => Math.max(1, Math.ceil(files.total / q.value.limit)))
const crumbs = computed(() => {
  const parts = q.value.folder.split('/').filter(Boolean)
  return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }))
})
const firstLoad = computed(() => files.loading && !files.items.length)

// The server filters by kind ("photos" is JPEG + RAW), so pages and totals are exact.
const MEDIA = new Set(['image', 'raw', 'video'])
const shown = computed(() => files.items.filter((f) => MEDIA.has(f.kind)))
const count = (n) => (n == null ? '' : ` ${n}`)
const modeOptions = computed(() => {
  const { photos, videos } = files.counts
  const all = photos == null || videos == null ? null : photos + videos
  return [
    { value: 'all', label: `All${count(all)}` },
    { value: 'photos', label: `Photos${count(photos)}` },
    { value: 'videos', label: `Videos${count(videos)}` },
  ]
})

async function load(params = {}) {
  failedLoad.value = false
  if (!storage.targetId) return // nothing to list yet: the empty state explains
  try {
    await files.load(params)
    files.loadCounts()
  } catch (e) {
    failedLoad.value = true
    if (!isNoTarget(e)) toasts.error(e)
  }
}
const stopSelecting = () => {
  selecting.value = false
  confirmDelete.value = false
  selected.value = new Set()
}
const goFolder = (folder) => {
  selected.value = new Set()
  return load({ folder, page: 1 })
}
const setFilter = (key, value) => load({ [key]: value, page: 1 })
const setMode = (m) => {
  mode.value = m
  selected.value = new Set()
  return setFilter('kind', { videos: 'video', photos: 'photos' }[m] || 'all')
}
const goPage = (page) => load({ page })

const EXT_KIND = { nef: 'raw', nrw: 'raw', mp4: 'video', mov: 'video' }
let pendingOpen = '' // a deep link seen before the storage target is known
async function openLinked(path) {
  if (!path) return
  if (!storage.targetId) {
    pendingOpen = path
    return
  }
  pendingOpen = ''
  const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
  if (q.value.folder !== dir || q.value.kind !== 'all' || q.value.page !== 1)
    await load({ folder: dir, kind: 'all', page: 1 })
  mode.value = 'all'
  const i = shown.value.findIndex((f) => f.path === path)
  if (i >= 0) {
    linked.value = null
    lightboxIndex.value = i
    return
  }
  const name = path.split('/').pop()
  linked.value = {
    path,
    name,
    folder: dir,
    size: 0,
    modified: null,
    kind: EXT_KIND[name.split('.').pop().toLowerCase()] || 'image',
    has_thumbnail: true,
  }
  lightboxIndex.value = 0
}
const closeLightbox = () => {
  lightboxIndex.value = -1
  linked.value = null
}
onMounted(async () => {
  await load()
  openLinked(props.openPath)
})
watch(() => props.openPath, openLinked)
watch(
  () => storage.targetId,
  (v, old) => {
    if (v === old) return
    // first target after a cold load: the pending link loads its own folder
    if (!old && pendingOpen) return openLinked(pendingOpen)
    if (!old) return load()
    return load({ folder: '', page: 1 })
  },
)

// Refresh when a capture lands or a job completes.
watch(
  () => capture.lastCapture,
  (v, old) => v && v !== old && load(),
)
watch(
  () =>
    jobs.list
      .filter((j) => j.status === 'completed')
      .map((j) => j.id)
      .join(','),
  (v, old) => v !== old && load(),
)
// Drop selections that vanished from the page.
watch(
  () => files.items,
  (items) => {
    const paths = new Set(items.map((f) => f.path))
    selected.value = new Set([...selected.value].filter((p) => paths.has(p)))
  },
)

function toggle(path) {
  const s = new Set(selected.value)
  s.has(path) ? s.delete(path) : s.add(path)
  selected.value = s
  confirmDelete.value = false
}
const allSelected = computed(
  () => shown.value.length > 0 && shown.value.every((f) => selected.value.has(f.path)),
)
function toggleAll() {
  selected.value = allSelected.value ? new Set() : new Set(shown.value.map((f) => f.path))
  confirmDelete.value = false
}

// Long-press (touch and pen) starts selecting; a mouse click selects only via the Select button.
let pressTimer = null
let longPressed = false
function pressStart(e, f) {
  longPressed = false
  if (e.pointerType === 'mouse') return
  clearTimeout(pressTimer)
  pressTimer = setTimeout(() => {
    longPressed = true
    selecting.value = true
    toggle(f.path)
  }, LONG_PRESS_MS)
}
const pressEnd = () => clearTimeout(pressTimer)
onUnmounted(pressEnd)
function onTile(f, i) {
  if (longPressed) {
    longPressed = false
    return
  }
  if (selecting.value) toggle(f.path)
  else {
    linked.value = null
    lightboxIndex.value = i
  }
}

async function download(item) {
  try {
    await files.download(item.path, item.name)
  } catch (e) {
    toasts.error(e)
  }
}
async function downloadSelected() {
  for (const f of shown.value) if (selected.value.has(f.path)) await download(f)
}

async function deleteMany(paths) {
  deleting.value = true
  const failures = []
  let ok = 0
  for (const p of paths) {
    try {
      await files.remove(p)
      ok++
    } catch (e) {
      failures.push(`${p.split('/').pop()}: ${e?.message || 'failed'}`)
    }
  }
  deleting.value = false
  confirmDelete.value = false
  selected.value = new Set([...selected.value].filter((p) => !paths.includes(p)))
  if (failures.length) {
    const head = failures.slice(0, 3).join('; ')
    const more = failures.length > 3 ? ` (+${failures.length - 3} more)` : ''
    toasts.error(`Could not delete ${failures.length} of ${paths.length} files: ${head}${more}`)
  } else if (ok) {
    toasts.success(ok === 1 ? 'File deleted' : `${ok} files deleted`)
  }
  files.loadCounts()
  return failures.length === 0
}

async function deleteFromLightbox(item) {
  const idx = lightboxIndex.value
  const ok = await deleteMany([item.path])
  if (!ok) return
  if (!shown.value.length || linked.value) closeLightbox()
  else lightboxIndex.value = Math.min(idx, shown.value.length - 1)
}

const emptyHint = computed(() =>
  files.folders.length
    ? 'Open a folder above.'
    : mode.value === 'videos'
      ? 'Rendered time-lapse videos appear here.'
      : 'Captured photos will appear here.',
)
</script>

<template>
  <NoTargetNotice v-if="noTarget" data-testid="no-target" />
  <div v-else class="space-y-4">
    <nav aria-label="Folder" class="flex flex-wrap items-center gap-1 text-sm">
      <button
        type="button"
        class="rounded-control px-1 hover:text-camera-text"
        :class="crumbs.length ? 'text-camera-muted' : 'text-camera-text'"
        @click="goFolder('')"
      >
        Output
      </button>
      <template v-for="(c, i) in crumbs" :key="c.path">
        <UiIcon name="ChevronRight" :size="14" class="text-camera-faint" />
        <button
          type="button"
          class="rounded-control px-1 hover:text-camera-text"
          :class="i === crumbs.length - 1 ? 'text-camera-text' : 'text-camera-muted'"
          @click="goFolder(c.path)"
        >
          {{ c.name }}
        </button>
      </template>
    </nav>

    <div v-if="files.folders.length" class="flex flex-wrap gap-2" data-testid="folders">
      <button
        v-for="f in files.folders"
        :key="f.path"
        type="button"
        class="inline-flex h-[var(--ctl-sm)] max-w-full items-center gap-2 rounded-control border border-camera-border bg-camera-raised px-3 text-[13px] hover:bg-camera-hover"
        @click="goFolder(f.path)"
      >
        <UiIcon name="Folder" :size="16" class="text-camera-muted" />
        <span class="truncate">{{ f.name }}</span>
      </button>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <UiSegmented
        size="sm"
        :model-value="mode"
        :options="modeOptions"
        aria-label="Show"
        @update:model-value="setMode"
      />
      <div class="toolbar-select">
        <UiSelect
          :model-value="q.sort"
          :options="SORTS"
          label="Sort"
          @update:model-value="setFilter('sort', $event)"
        />
      </div>
      <div class="toolbar-select">
        <UiSelect
          :model-value="q.limit"
          :options="LIMITS"
          label="Page size"
          @update:model-value="setFilter('limit', Number($event))"
        />
      </div>
      <span class="flex-1" />
      <div v-if="selecting" class="flex flex-wrap items-center gap-2" data-testid="select-bar">
        <span class="tabular-nums text-sm" aria-live="polite">{{ selected.size }} selected</span>
        <UiButton size="sm" @click="toggleAll">{{ allSelected ? 'Clear' : 'Select all' }}</UiButton>
        <UiButton size="sm" :disabled="!selected.size" @click="downloadSelected">
          <UiIcon name="Download" :size="16" />Download
        </UiButton>
        <template v-if="confirmDelete">
          <UiButton
            size="sm"
            variant="danger"
            :loading="deleting"
            @click="deleteMany([...selected])"
          >
            Delete {{ selected.size }} {{ selected.size === 1 ? 'item' : 'items' }}
          </UiButton>
          <UiButton size="sm" variant="ghost" @click="confirmDelete = false">Keep</UiButton>
        </template>
        <UiButton v-else size="sm" :disabled="!selected.size" @click="confirmDelete = true">
          <UiIcon name="Trash2" :size="16" />Delete
        </UiButton>
        <UiButton size="sm" variant="ghost" @click="stopSelecting">Done</UiButton>
      </div>
      <UiButton v-else size="sm" :disabled="!shown.length" @click="selecting = true">
        Select
      </UiButton>
    </div>
    <p
      v-if="shown.length && !selecting"
      class="hidden text-[12.5px] text-camera-muted [html[data-layout='touch']_&]:block"
    >
      Tip: press and hold a photo to start selecting.
    </p>

    <div
      v-if="firstLoad"
      class="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3"
      aria-busy="true"
    >
      <div
        v-for="n in 10"
        :key="n"
        class="aspect-[3/2] animate-pulse rounded-inner bg-camera-raised"
      />
    </div>

    <UiEmpty v-else-if="failedLoad && !files.items.length" title="Could not load files">
      <template #actions><UiButton @click="load()">Retry</UiButton></template>
    </UiEmpty>

    <UiEmpty
      v-else-if="!shown.length"
      :title="mode === 'videos' ? 'No videos here' : 'No files here'"
      :hint="emptyHint"
    />

    <ul
      v-else
      class="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3 [html[data-layout='touch']_&]:grid-cols-[repeat(auto-fill,minmax(150px,1fr))]"
      data-testid="grid"
    >
      <li
        v-for="(f, i) in shown"
        :key="f.path"
        class="relative grid grid-cols-[minmax(0,1fr)] overflow-hidden rounded-inner border bg-camera-surface"
        :class="
          selected.has(f.path)
            ? 'border-camera-accent outline outline-2 -outline-offset-2 outline-camera-accent'
            : 'border-camera-subtle hover:border-camera-border'
        "
      >
        <button
          type="button"
          class="relative block aspect-[3/2] w-full select-none bg-black p-0"
          :aria-label="selecting ? `Select ${f.name}` : `Open ${f.name}`"
          :aria-pressed="selecting ? selected.has(f.path) : undefined"
          @pointerdown="pressStart($event, f)"
          @pointerup="pressEnd"
          @pointerleave="pressEnd"
          @pointercancel="pressEnd"
          @contextmenu.prevent
          @click="onTile(f, i)"
        >
          <Thumb :path="f.path" :supported="f.has_thumbnail" :alt="f.name" />
          <span
            v-if="f.kind === 'video'"
            class="pointer-events-none absolute inset-0 flex items-center justify-center text-white"
          >
            <UiIcon name="Play" :size="36" />
          </span>
          <span
            v-if="selecting"
            aria-hidden="true"
            class="absolute left-2.5 top-2.5 inline-flex h-6 w-6 items-center justify-center rounded-control border-2 border-white text-camera-accent-ink [html[data-layout='touch']_&]:h-[30px] [html[data-layout='touch']_&]:w-[30px]"
            :class="selected.has(f.path) ? 'border-camera-accent bg-camera-accent' : 'bg-black/35'"
          >
            <UiIcon v-if="selected.has(f.path)" name="Check" :size="16" />
          </span>
        </button>
        <div class="grid min-w-0 gap-0.5 px-2.5 py-2 text-xs">
          <div class="flex min-w-0 items-center justify-between gap-2">
            <p class="min-w-0 truncate font-mono font-medium" :title="f.name">{{ f.name }}</p>
            <UiBadge :tone="kindTone(f.kind)">{{ fileKind(f.kind) }}</UiBadge>
          </div>
          <p class="truncate tabular-nums text-camera-muted">
            {{ formatSize(f.size) }} · {{ formatDate(f.modified) }}
          </p>
        </div>
      </li>
    </ul>

    <div v-if="files.total > q.limit" class="flex items-center justify-center gap-3">
      <UiButton size="sm" :disabled="q.page <= 1 || files.loading" @click="goPage(q.page - 1)">
        Previous
      </UiButton>
      <span class="tabular-nums text-sm text-camera-muted">Page {{ q.page }} of {{ pages }}</span>
      <UiButton size="sm" :disabled="q.page >= pages || files.loading" @click="goPage(q.page + 1)">
        Next
      </UiButton>
    </div>

    <Lightbox
      :open="lightboxIndex >= 0"
      :items="lightboxItems"
      :index="Math.max(0, lightboxIndex)"
      :busy="deleting"
      @update:index="lightboxIndex = $event"
      @close="closeLightbox"
      @download="download"
      @delete="deleteFromLightbox"
    />
  </div>
</template>

<style scoped>
/* Toolbar selects: label is visually hidden and the control matches the small segmented height */
.toolbar-select :deep(label) {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
.toolbar-select :deep(select) {
  height: var(--ctl-sm);
  font-size: 13px;
}
</style>
