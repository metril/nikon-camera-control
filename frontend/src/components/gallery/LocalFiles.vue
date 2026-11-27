<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiCheck from '@/components/ui/UiCheck.vue'
import SelectionBar from './SelectionBar.vue'
import CopyToDialog from './CopyToDialog.vue'
import { useSelection } from '@/composables/useSelection'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { useFilesStore } from '@/stores/files'
import { useCaptureStore } from '@/stores/capture'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'
import { isNoTarget } from '@/api'
import { fileKind, storageName } from '@/labels'
import { useVideosStore } from '@/stores/videos'
import Videos from './Videos.vue'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import Thumb from './Thumb.vue'
import Lightbox from './Lightbox.vue'
import { formatSize, formatDate, kindTone, isSystemFolder } from './media'

const props = defineProps({ openPath: { type: String, default: '' } })

const files = useFilesStore()
const capture = useCaptureStore()
const jobs = useJobsStore()
const toasts = useToastsStore()
const storage = useStorageStore()
const videosStore = useVideosStore()

const { isTouch } = useLayoutMode()
const COLS_KEY = 'nikon-gallery-cols'
const readCols = () => {
  try {
    const n = Number(localStorage.getItem(COLS_KEY))
    return n >= 3 && n <= 10 ? n : 7
  } catch {
    return 7
  }
}
const cols = ref(readCols())
watch(cols, (n) => {
  try {
    localStorage.setItem(COLS_KEY, String(n))
  } catch {
    /* remembered per viewer when possible */
  }
})
const nameFilter = ref('')

const SORTS = [
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'name', label: 'Name' },
]
const LIMITS = [24, 50, 100, 200].map((n) => ({ value: n, label: `${n} per page` }))

const mode = ref('all') // all | photos | videos | timelapses
const rootName = computed(() => storageName(storage.target))
const folders = computed(() => files.folders.filter((f) => !isSystemFolder(f.name)))
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
const shown = computed(() => {
  const needle = nameFilter.value.trim().toLowerCase()
  return files.items.filter(
    (f) => MEDIA.has(f.kind) && (!needle || f.name.toLowerCase().includes(needle)),
  )
})
const sel = useSelection({ ids: () => shown.value.map((f) => f.path) })
const copying = ref(false)
const copyOpen = ref(false)
const count = (n) => (n == null ? '' : ` ${n}`)
const modeOptions = computed(() => {
  const { photos, videos } = files.counts
  const all = photos == null || videos == null ? null : photos + videos
  return [
    { value: 'all', label: `All${count(all)}` },
    { value: 'photos', label: `Photos${count(photos)}` },
    { value: 'videos', label: `Videos${count(videos)}` },
    { value: 'timelapses', label: `Time-lapses${count(videosStore.total)}` },
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
const goFolder = (folder) => {
  sel.clear()
  return load({ folder, page: 1 })
}
const setFilter = (key, value) => load({ [key]: value, page: 1 })
const setMode = (m) => {
  mode.value = m
  sel.clear()
  if (m === 'timelapses') return
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
  if (storage.targetId) videosStore.fetch().catch(() => {})
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
// Long-press (touch and pen) starts selecting; a mouse uses Select, Ctrl/Shift-click or the check.
const pressers = new Map()
watch(shown, () => pressers.clear())
function press(path) {
  let h = pressers.get(path)
  if (!h) {
    const lp = sel.longPress(path)
    h = { ...lp, onPointerdown: (e) => e.pointerType !== 'mouse' && lp.onPointerdown(e) }
    pressers.set(path, h)
  }
  return h
}
function onTile(f, i, e) {
  if (sel.click(f.path, e)) return
  linked.value = null
  lightboxIndex.value = i
}
const onCheck = (f, e) => sel.toggle(f.path, { shift: e?.shiftKey })

async function download(item) {
  try {
    await files.download(item.path, item.name)
  } catch (e) {
    toasts.error(e)
  }
}
async function zipSelected() {
  try {
    await files.downloadZip(sel.list.value)
  } catch (e) {
    toasts.error(e)
  }
}

async function deleteMany(paths) {
  deleting.value = true
  let out
  try {
    out = await files.removeMany(paths)
  } catch (e) {
    toasts.error(e)
    return false
  } finally {
    deleting.value = false
  }
  const ok = out.deleted.length
  const failures = out.failed.map((f) => `${f.path.split('/').pop()}: ${f.error || 'failed'}`)
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

async function copyTo(toId) {
  const paths = sel.list.value
  copying.value = true
  try {
    await storage.offload({
      from_id: storage.targetId,
      to_id: toId,
      scope: { kind: 'files', paths },
      keep_source: true,
    })
    toasts.success(`Copying ${paths.length} ${paths.length === 1 ? 'file' : 'files'}`)
    copyOpen.value = false
    sel.clear()
  } catch (e) {
    toasts.error(e)
  } finally {
    copying.value = false
  }
}

async function deleteFromLightbox(item) {
  const idx = lightboxIndex.value
  const ok = await deleteMany([item.path])
  if (!ok) return
  if (!shown.value.length || linked.value) closeLightbox()
  else lightboxIndex.value = Math.min(idx, shown.value.length - 1)
}

const emptyHint = computed(() =>
  folders.value.length
    ? 'Open a folder above.'
    : mode.value === 'videos'
      ? 'Rendered time-lapse videos appear here.'
      : 'Captured photos will appear here.',
)
</script>

<template>
  <NoTargetNotice v-if="noTarget" data-testid="no-target" />
  <div v-else class="flex min-h-0 flex-1 flex-col gap-3">
    <!-- At the root the source card already names the drive: crumbs only inside folders -->
    <nav
      v-if="crumbs.length"
      aria-label="Folder"
      class="flex shrink-0 flex-wrap items-center gap-x-1 text-sm"
    >
      <button
        type="button"
        class="crumb"
        :class="crumbs.length ? 'text-camera-muted' : 'text-camera-text'"
        @click="goFolder('')"
      >
        {{ rootName }}
      </button>
      <template v-for="(c, i) in crumbs" :key="c.path">
        <UiIcon name="ChevronRight" :size="14" class="text-camera-faint" />
        <button
          type="button"
          class="crumb"
          :class="i === crumbs.length - 1 ? 'text-camera-text' : 'text-camera-muted'"
          @click="goFolder(c.path)"
        >
          {{ c.name }}
        </button>
      </template>
    </nav>

    <div
      v-if="folders.length && mode !== 'timelapses'"
      class="scroll-panel flex max-h-[96px] shrink-0 flex-wrap gap-2"
      data-testid="folders"
    >
      <button
        v-for="f in folders"
        :key="f.path"
        type="button"
        class="inline-flex h-[var(--ctl-sm)] max-w-full items-center gap-2 rounded-control border border-camera-border bg-camera-raised px-3 text-[13px] hover:bg-camera-hover"
        @click="goFolder(f.path)"
      >
        <UiIcon name="Folder" :size="16" class="text-camera-muted" />
        <span class="truncate">{{ f.name }}</span>
      </button>
    </div>

    <SelectionBar
      v-if="sel.selecting.value && mode !== 'timelapses' && isTouch"
      :count="sel.count.value"
      :all-selected="sel.allSelected.value"
      :busy="deleting || copying"
      @toggle-all="sel.allSelected.value ? sel.clear() : sel.selectAll()"
      @copy="copyOpen = true"
      @delete="deleteMany(sel.list.value)"
      @done="sel.clear()"
    />
    <div v-else class="flex shrink-0 flex-wrap items-center gap-3">
      <UiSegmented
        size="sm"
        :model-value="mode"
        :options="modeOptions"
        aria-label="Show"
        @update:model-value="setMode"
      />
      <template v-if="mode !== 'timelapses'">
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
        <label
          v-if="!isTouch"
          class="flex h-[var(--ctl-sm)] w-[220px] items-center gap-2 rounded-control border border-camera-border bg-camera-bg px-2.5"
        >
          <svg
            aria-hidden="true"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            class="text-camera-muted"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4-4" />
          </svg>
          <input
            v-model="nameFilter"
            type="search"
            placeholder="Filter by name"
            aria-label="Filter by name"
            class="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
          />
        </label>
        <span class="flex-1" />
        <label v-if="!isTouch" class="flex items-center gap-2 text-[13px] text-camera-muted">
          Size
          <input
            v-model.number="cols"
            type="range"
            min="3"
            max="10"
            aria-label="Thumbnail size"
            class="w-[120px] accent-camera-accent"
            style="direction: rtl"
          />
        </label>
        <span class="tabular-nums text-[13px] text-camera-muted" data-testid="count">
          {{ files.total.toLocaleString() }} {{ files.total === 1 ? 'file' : 'files' }}
        </span>
        <UiButton size="sm" :disabled="!shown.length" data-testid="select" @click="sel.start(null)">
          Select
        </UiButton>
      </template>
    </div>
    <SelectionBar
      v-if="sel.selecting.value && mode !== 'timelapses' && !isTouch"
      :count="sel.count.value"
      :all-selected="sel.allSelected.value"
      :busy="deleting || copying"
      @toggle-all="sel.allSelected.value ? sel.clear() : sel.selectAll()"
      @zip="zipSelected"
      @copy="copyOpen = true"
      @delete="deleteMany(sel.list.value)"
      @done="sel.clear()"
    />

    <Videos v-if="mode === 'timelapses'" class="min-h-0 flex-1" />
    <template v-else>
      <div
        class="scroll-panel min-h-0 flex-1 rounded-card border border-camera-subtle bg-camera-surface p-3 [html[data-layout='touch']_&]:p-4"
        tabindex="0"
        aria-label="Photos"
      >
        <p
          v-if="shown.length && !sel.selecting.value"
          class="mb-3 hidden text-[12.5px] text-camera-muted [html[data-layout='touch']_&]:block"
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
          class="grid gap-3 [html[data-layout='touch']_&]:grid-cols-[repeat(auto-fill,minmax(200px,1fr))] [html[data-layout='touch']_&]:gap-3.5"
          :style="isTouch ? null : { gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }"
          data-testid="grid"
        >
          <li
            v-for="(f, i) in shown"
            :key="f.path"
            class="group relative grid grid-cols-[minmax(0,1fr)] overflow-hidden rounded-inner border bg-camera-bg"
            :class="
              sel.isSelected(f.path)
                ? 'border-camera-accent outline outline-2 -outline-offset-2 outline-camera-accent'
                : 'border-camera-subtle hover:border-camera-border'
            "
          >
            <button
              type="button"
              class="relative block aspect-[3/2] w-full select-none bg-black p-0"
              :aria-label="sel.selecting.value ? `Select ${f.name}` : `Open ${f.name}`"
              :aria-pressed="sel.selecting.value ? sel.isSelected(f.path) : undefined"
              v-bind="press(f.path)"
              @click="onTile(f, i, $event)"
            >
              <Thumb :path="f.path" :supported="f.has_thumbnail" :alt="f.name" />
              <span
                v-if="f.kind === 'video'"
                class="pointer-events-none absolute inset-0 flex items-center justify-center text-white"
              >
                <UiIcon name="Play" :size="36" />
              </span>
            </button>
            <UiCheck
              v-if="sel.selecting.value || !isTouch"
              :model-value="sel.isSelected(f.path)"
              :label="`Toggle ${f.name}`"
              class="absolute left-2 top-2"
              :class="
                sel.selecting.value
                  ? ''
                  : 'opacity-0 focus-visible:opacity-100 group-hover:opacity-100'
              "
              @click="onCheck(f, $event)"
            />
            <div
              class="grid min-w-0 gap-0.5 px-2.5 py-2 text-xs [html[data-layout='touch']_&]:text-[length:var(--fs-min)]"
            >
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
      </div>

      <div
        v-if="files.total > q.limit"
        class="flex shrink-0 items-center justify-center gap-3"
        data-testid="pager"
      >
        <UiButton size="sm" :disabled="q.page <= 1 || files.loading" @click="goPage(q.page - 1)">
          Previous
        </UiButton>
        <span class="tabular-nums text-sm text-camera-muted">Page {{ q.page }} of {{ pages }}</span>
        <UiButton
          size="sm"
          :disabled="q.page >= pages || files.loading"
          @click="goPage(q.page + 1)"
        >
          Next
        </UiButton>
      </div>
    </template>

    <CopyToDialog
      :open="copyOpen"
      :count="sel.count.value"
      :busy="copying"
      @close="copyOpen = false"
      @confirm="copyTo"
    />
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
.crumb {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 6px;
  border-radius: var(--radius-control, 6px);
}
.crumb:hover {
  color: var(--camera-text, #fff);
}
html[data-layout='touch'] .crumb {
  min-height: 44px;
}
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
