<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import { useFilesStore } from '@/stores/files'
import { useCaptureStore } from '@/stores/capture'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'
import { isNoTarget } from '@/api'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import Thumb from './Thumb.vue'
import Lightbox from './Lightbox.vue'
import { formatSize, formatDate, kindTone } from './media'

const files = useFilesStore()
const capture = useCaptureStore()
const jobs = useJobsStore()
const toasts = useToastsStore()
const storage = useStorageStore()

const KINDS = [
  { value: 'all', label: 'All' },
  { value: 'image', label: 'Images' },
  { value: 'raw', label: 'RAW' },
  { value: 'video', label: 'Video' },
]
const SORTS = [
  { value: 'newest', label: 'Newest' },
  { value: 'oldest', label: 'Oldest' },
  { value: 'name', label: 'Name' },
]
const LIMITS = [24, 50, 100, 200].map((n) => ({ value: n, label: `${n} per page` }))

const selected = ref(new Set())
const lightboxIndex = ref(-1)
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

async function load(params = {}) {
  failedLoad.value = false
  try {
    await files.load(params)
  } catch (e) {
    failedLoad.value = true
    if (!isNoTarget(e)) toasts.error(e)
  }
}
const goFolder = (folder) => {
  selected.value = new Set()
  return load({ folder, page: 1 })
}
const setFilter = (key, value) => load({ [key]: value, page: 1 })
const goPage = (page) => load({ page })

onMounted(() => load())
watch(
  () => storage.targetId,
  (v, old) => v !== old && load({ folder: '', page: 1 }),
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
}

async function download(item) {
  try {
    await files.download(item.path, item.name)
  } catch (e) {
    toasts.error(e)
  }
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
  selected.value = new Set([...selected.value].filter((p) => !paths.includes(p)))
  if (failures.length) {
    const head = failures.slice(0, 3).join('; ')
    const more = failures.length > 3 ? ` (+${failures.length - 3} more)` : ''
    toasts.error(`Could not delete ${failures.length} of ${paths.length} files: ${head}${more}`)
  } else if (ok) {
    toasts.success(ok === 1 ? 'File deleted' : `${ok} files deleted`)
  }
  return failures.length === 0
}

async function deleteFromLightbox(item) {
  const idx = lightboxIndex.value
  const ok = await deleteMany([item.path])
  if (!ok) return
  if (!files.items.length) lightboxIndex.value = -1
  else lightboxIndex.value = Math.min(idx, files.items.length - 1)
}
</script>

<template>
  <NoTargetNotice v-if="noTarget" data-testid="no-target" />
  <div v-else class="space-y-4">
    <nav aria-label="Folder" class="flex flex-wrap items-center gap-1 text-sm">
      <button
        type="button"
        class="rounded px-1 text-sky-400 hover:underline focus-visible:ring-2 focus-visible:ring-sky-500"
        @click="goFolder('')"
      >
        Output
      </button>
      <template v-for="c in crumbs" :key="c.path">
        <span class="text-slate-600" aria-hidden="true">/</span>
        <button
          type="button"
          class="rounded px-1 text-sky-400 hover:underline focus-visible:ring-2 focus-visible:ring-sky-500"
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
        class="rounded border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 focus-visible:ring-2 focus-visible:ring-sky-500"
        @click="goFolder(f.path)"
      >
        📁 {{ f.name }}
      </button>
    </div>

    <div class="flex flex-wrap items-end gap-3">
      <UiSegmented
        :model-value="q.kind"
        :options="KINDS"
        aria-label="Filter by kind"
        @update:model-value="setFilter('kind', $event)"
      />
      <UiSelect
        :model-value="q.sort"
        :options="SORTS"
        label="Sort"
        @update:model-value="setFilter('sort', $event)"
      />
      <UiSelect
        :model-value="q.limit"
        :options="LIMITS"
        label="Page size"
        @update:model-value="setFilter('limit', Number($event))"
      />
      <div class="ml-auto flex items-center gap-2">
        <span class="text-sm text-slate-400" aria-live="polite">{{ files.total }} files</span>
        <UiConfirmButton
          v-if="selected.size"
          variant="danger"
          size="sm"
          :loading="deleting"
          :confirm-text="`Delete ${selected.size}?`"
          @confirm="deleteMany([...selected])"
        >
          Delete selected ({{ selected.size }})
        </UiConfirmButton>
      </div>
    </div>

    <div
      v-if="firstLoad"
      class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5"
      aria-busy="true"
    >
      <div v-for="n in 10" :key="n" class="aspect-square animate-pulse rounded bg-slate-800" />
    </div>

    <UiEmpty v-else-if="failedLoad && !files.items.length" title="Could not load files">
      <template #actions><UiButton @click="load()">Retry</UiButton></template>
    </UiEmpty>

    <UiEmpty
      v-else-if="!files.items.length"
      title="No files here"
      :hint="files.folders.length ? 'Open a folder above.' : 'Captured photos will appear here.'"
    />

    <ul v-else class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" data-testid="grid">
      <li
        v-for="(f, i) in files.items"
        :key="f.path"
        class="overflow-hidden rounded border border-slate-700 bg-slate-800"
      >
        <div class="relative aspect-square">
          <button
            type="button"
            class="block h-full w-full focus-visible:ring-2 focus-visible:ring-sky-500"
            :aria-label="`Open ${f.name}`"
            @click="lightboxIndex = i"
          >
            <Thumb :path="f.path" :supported="f.has_thumbnail" :alt="f.name" />
          </button>
          <input
            type="checkbox"
            class="absolute left-2 top-2 h-4 w-4"
            :checked="selected.has(f.path)"
            :aria-label="`Select ${f.name}`"
            @change="toggle(f.path)"
          />
          <UiBadge class="absolute right-2 top-2" :tone="kindTone(f.kind)">{{ f.kind }}</UiBadge>
        </div>
        <div class="p-2 text-xs">
          <p class="truncate text-slate-200" :title="f.name">{{ f.name }}</p>
          <p class="text-slate-400">{{ formatSize(f.size) }} · {{ formatDate(f.modified) }}</p>
        </div>
      </li>
    </ul>

    <div v-if="files.total > q.limit" class="flex items-center justify-center gap-3">
      <UiButton size="sm" :disabled="q.page <= 1 || files.loading" @click="goPage(q.page - 1)">
        Previous
      </UiButton>
      <span class="text-sm text-slate-400">Page {{ q.page }} of {{ pages }}</span>
      <UiButton size="sm" :disabled="q.page >= pages || files.loading" @click="goPage(q.page + 1)">
        Next
      </UiButton>
    </div>

    <Lightbox
      :open="lightboxIndex >= 0"
      :items="files.items"
      :index="Math.max(0, lightboxIndex)"
      :busy="deleting"
      @update:index="lightboxIndex = $event"
      @close="lightboxIndex = -1"
      @download="download"
      @delete="deleteFromLightbox"
    />
  </div>
</template>
