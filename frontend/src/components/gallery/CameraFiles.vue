<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import CameraThumb from './CameraThumb.vue'
import { fileKind, leaseOwner } from '@/labels'
import { useCameraStore } from '@/stores/camera'
import { useCameraFilesStore } from '@/stores/cameraFiles'
import { useJobsStore } from '@/stores/jobs'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import { formatSize, formatDate } from './media'

const camera = useCameraStore()
const cf = useCameraFilesStore()
const jobs = useJobsStore()
const storage = useStorageStore()
const toasts = useToastsStore()

// 'flat': every file under DCIM in one list. 'folders': browse the card folder by folder.
const view = ref('flat')
const VIEWS = [
  { value: 'flat', label: 'All files' },
  { value: 'folders', label: 'By folder' },
]
const optionsOpen = ref(false)
const onlyNew = ref(true)
const deleteAfter = ref(false)
const jobId = ref(null)
const starting = ref(false)
const cancelling = ref(false)
const busyFile = ref(null)
const failedLoad = ref(false)

const folder = computed(() => cf.query.folder)
const pages = computed(() => Math.max(1, Math.ceil(cf.total / cf.query.limit)))
const leased = computed(() => !!camera.leasedBy)
const leaseReason = computed(() =>
  leased.value ? `Busy: ${leaseOwner(camera.leasedBy)} is using the camera` : '',
)
const subfolders = ref([])
// The camera's own "store_XXXXXXXX" level is an implementation detail: never shown as a folder.
const isStore = (n) => /^store_/i.test(n)
const storeRoot = ref('/')
const storeNames = ref([]) // every store_* level on the card root, in listing order
const cards = computed(() => camera.storage?.cards || [])
// A store is named by what the camera reports for its card; "Card N" only when it reports none.
function storeLabel(name) {
  const card = cards.value.find((c) => c.base_dir?.split('/').filter(Boolean).pop() === name)
  return card?.label || `Card ${storeNames.value.indexOf(name) + 1 || 1}`
}
const crumbs = computed(() => {
  const parts = folder.value.split('/').filter(Boolean)
  const several = storeNames.value.length > 1
  return parts
    .map((name, i) => ({
      name: i === 0 && isStore(name) ? storeLabel(name) : name,
      path: '/' + parts.slice(0, i + 1).join('/'),
      store: i === 0 && isStore(name),
    }))
    .filter((c) => !c.store || several)
})

const job = computed(() => {
  if (jobId.value) return jobs.byId[jobId.value] || null
  return jobs.active.find((j) => j.kind === 'download_all') || null
})
const running = computed(() => job.value && ['queued', 'running'].includes(job.value.status))
const result = computed(() => (job.value && !running.value ? job.value.result : null))

async function load(params = {}) {
  failedLoad.value = false
  try {
    await cf.loadFiles(params)
    if (view.value === 'folders' && (params.folder !== undefined || !subfolders.value.length)) {
      let out = (await cf.loadFolders(folder.value))?.folders || []
      if (folder.value === '/')
        storeNames.value = out.filter((f) => isStore(f.name)).map((f) => f.name)
      // Step over the lone store_* folder on the card root so the first level is DCIM.
      if (folder.value === '/' && out.length === 1 && isStore(out[0].name)) {
        storeRoot.value = out[0].path
        await cf.loadFiles({ folder: storeRoot.value, page: 1 })
        out = (await cf.loadFolders(storeRoot.value))?.folders || []
      }
      subfolders.value = out
    }
  } catch (e) {
    failedLoad.value = true
    toasts.error(e)
  }
}
const goFolder = (f) => load({ folder: f, page: 1, recursive: false })
function setView(v) {
  view.value = v
  subfolders.value = []
  if (v === 'flat') return load({ folder: '/', recursive: true, page: 1 })
  return load({ folder: '/', recursive: false, page: 1 })
}

function init() {
  if (!camera.connected) return
  camera.fetchStorage().catch((e) => toasts.error(e))
  load(view.value === 'flat' ? { folder: '/', recursive: true, page: 1 } : {})
}
onMounted(init)
onMounted(() => !storage.loaded && storage.refresh().catch(() => {}))
watch(() => camera.connected, init)
// Refresh the listing once a download-all job finishes.
watch(
  () => job.value?.status,
  (s, old) => {
    if (old && s === 'completed') {
      load()
      camera.fetchStorage().catch(() => {})
    }
  },
)

const fileKey = (f) => `${f.folder}/${f.name}`
async function downloadOne(f) {
  busyFile.value = fileKey(f)
  try {
    await cf.download(f.folder, f.name)
  } catch (e) {
    toasts.error(e)
  } finally {
    busyFile.value = null
  }
}
async function removeOne(f) {
  busyFile.value = fileKey(f)
  try {
    await cf.remove(f.folder, f.name)
    toasts.success(`Deleted ${f.name} from the card`)
  } catch (e) {
    toasts.error(e)
  } finally {
    busyFile.value = null
  }
}
async function startAll() {
  starting.value = true
  try {
    const j = await cf.downloadAll({
      only_new: onlyNew.value,
      delete_after: deleteAfter.value,
      folder: view.value === 'flat' || folder.value === '/' ? null : folder.value,
    })
    jobs.upsert(j)
    jobId.value = j.id
  } catch (e) {
    toasts.error(e)
  } finally {
    starting.value = false
  }
}
async function cancel() {
  cancelling.value = true
  try {
    await jobs.cancel(job.value.id)
  } catch (e) {
    toasts.error(e)
  } finally {
    cancelling.value = false
  }
}
const noStorage = computed(() => storage.noTarget)
const gb = (kb) => formatSize(kb * 1024)
</script>

<template>
  <UiEmpty
    v-if="!camera.connected"
    title="Camera not connected"
    hint="Connect the camera to browse files on its card."
  >
    <template #actions>
      <UiButton variant="primary" @click="camera.connect().catch((e) => toasts.error(e))">
        Connect
      </UiButton>
    </template>
  </UiEmpty>

  <div v-else class="space-y-4">
    <div v-if="cards.length" class="flex flex-wrap gap-3" data-testid="storage">
      <div
        v-for="c in cards"
        :key="c.base_dir || c.label"
        class="rounded-inner border border-camera-border bg-camera-raised px-3 py-2 text-sm text-camera-muted"
      >
        <span class="font-medium text-camera-text">{{ c.label }}</span>
        · <span class="tabular-nums">{{ gb(c.free_kb) }} free of {{ gb(c.capacity_kb) }}</span>
      </div>
    </div>

    <div class="rounded-card border border-camera-border bg-camera-surface p-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="mr-auto text-sm font-semibold">Download all to storage</span>
        <UiButton
          size="sm"
          variant="ghost"
          :aria-expanded="optionsOpen"
          :disabled="running"
          data-testid="download-options"
          @click="optionsOpen = !optionsOpen"
        >
          Options
          <UiIcon :name="optionsOpen ? 'ChevronUp' : 'ChevronDown'" :size="14" />
        </UiButton>
        <UiButton
          v-if="!running"
          variant="primary"
          size="sm"
          :loading="starting"
          :disabled="leased || noStorage"
          :title="noStorage ? 'Choose a storage first' : leaseReason"
          data-testid="download-all"
          @click="startAll"
        >
          Download all
        </UiButton>
      </div>
      <div v-if="optionsOpen" class="mt-3 space-y-3" data-testid="download-options-panel">
        <div class="flex flex-wrap gap-x-6 gap-y-1">
          <UiToggle v-model="onlyNew" label="Only new files" :disabled="running" />
          <UiToggle
            v-model="deleteAfter"
            label="Delete from card after download"
            :disabled="running"
          />
        </div>
        <UiAlert v-if="deleteAfter" tone="warn">
          Files are removed from the card once saved to storage.
        </UiAlert>
      </div>
      <p v-if="leased" class="mt-2 text-sm text-camera-warn">{{ leaseReason }}</p>
      <NoTargetNotice v-if="noStorage" compact class="mt-2" />
      <div v-if="running" class="mt-3 space-y-2" aria-live="polite" data-testid="job-progress">
        <UiProgress :value="job.progress ?? null" :label="job.message || 'Downloading'" />
        <p class="text-sm text-camera-muted">{{ job.message }}</p>
        <UiButton variant="danger" size="sm" :loading="cancelling" @click="cancel">Cancel</UiButton>
      </div>
      <p v-if="job?.status === 'failed'" class="mt-2 text-sm text-camera-danger" role="alert">
        Download failed: {{ job.error || 'unknown error' }}
      </p>
      <p
        v-if="result"
        class="mt-2 tabular-nums text-sm text-camera-muted"
        data-testid="job-result"
        aria-live="polite"
      >
        {{ result.cancelled ? 'Cancelled. ' : '' }}Downloaded {{ result.downloaded }} · skipped
        {{ result.skipped }} · failed {{ result.failed }}
        <span v-if="result.failed_names?.length" class="text-camera-danger">
          ({{ result.failed_names.join(', ') }})
        </span>
      </p>
    </div>

    <UiSegmented
      size="sm"
      :model-value="view"
      :options="VIEWS"
      aria-label="Card view"
      @update:model-value="setView"
    />

    <template v-if="view === 'folders'">
      <nav aria-label="Card folder" class="flex flex-wrap items-center gap-1 text-sm">
        <button
          type="button"
          class="crumb"
          :class="crumbs.length ? 'text-camera-muted' : 'text-camera-text'"
          @click="goFolder(storeRoot)"
        >
          Card
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
      <div v-if="subfolders.length" class="flex flex-wrap gap-2" data-testid="card-folders">
        <button
          v-for="f in subfolders"
          :key="f.path"
          type="button"
          class="inline-flex h-[var(--ctl-sm)] max-w-full items-center gap-2 rounded-control border border-camera-border bg-camera-raised px-3 text-[13px] hover:bg-camera-hover"
          @click="goFolder(f.path)"
        >
          <UiIcon name="Folder" :size="16" class="text-camera-muted" />
          <span class="truncate">{{ isStore(f.name) ? storeLabel(f.name) : f.name }}</span>
        </button>
      </div>
    </template>

    <div v-if="cf.loading && !cf.items.length" class="space-y-2" aria-busy="true">
      <div v-for="n in 6" :key="n" class="h-10 animate-pulse rounded-inner bg-camera-raised" />
    </div>
    <UiEmpty v-else-if="failedLoad && !cf.items.length" title="Could not list the card">
      <template #actions><UiButton @click="load()">Retry</UiButton></template>
    </UiEmpty>
    <UiEmpty v-else-if="!cf.items.length" title="No files here" />
    <div v-else class="text-sm" role="list" data-testid="card-files">
      <div class="file-row eyebrow max-[640px]:!hidden" aria-hidden="true">
        <span />
        <span>Name</span>
        <span>Size</span>
        <span>Date</span>
        <span>Type</span>
        <span />
      </div>
      <div
        v-for="f in cf.items"
        :key="f.folder + '/' + f.name"
        role="listitem"
        class="file-row border-t border-camera-subtle"
        data-testid="card-file"
      >
        <span class="thumb">
          <CameraThumb :folder="f.folder" :name="f.name" :supported="f.type !== 'video'" />
        </span>
        <span class="flex min-w-0 items-center gap-2">
          <span class="truncate font-mono text-[13px]" :title="f.folder + '/' + f.name">{{
            f.name
          }}</span>
          <UiBadge v-if="f.downloaded" tone="ok">Downloaded</UiBadge>
        </span>
        <span class="tabular-nums text-camera-muted">{{ formatSize(f.size) }}</span>
        <span class="tabular-nums text-camera-muted">{{ formatDate(f.mtime) }}</span>
        <span class="text-camera-muted">{{ fileKind(f.type) }}</span>
        <span class="actions">
          <UiButton size="sm" :loading="busyFile === fileKey(f)" @click="downloadOne(f)">
            <UiIcon name="Download" :size="16" />Download
          </UiButton>
          <UiConfirmButton
            size="sm"
            variant="danger"
            data-testid="delete-card-file"
            :disabled="leased || busyFile === fileKey(f)"
            :title="leaseReason"
            @confirm="removeOne(f)"
          >
            Delete
          </UiConfirmButton>
        </span>
      </div>
    </div>

    <div v-if="cf.total > cf.query.limit" class="flex items-center justify-center gap-3">
      <UiButton size="sm" :disabled="cf.query.page <= 1" @click="load({ page: cf.query.page - 1 })">
        Previous
      </UiButton>
      <span class="tabular-nums text-sm text-camera-muted"
        >Page {{ cf.query.page }} of {{ pages }}</span
      >
      <UiButton
        size="sm"
        :disabled="cf.query.page >= pages"
        @click="load({ page: cf.query.page + 1 })"
      >
        Next
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
/* One grid for header and rows: thumbnail, name, size, date, type, fixed actions column.
   On phones a row becomes a card: thumbnail and name, meta line, then actions. */
.file-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) 80px 170px 64px 200px;
  align-items: center;
  gap: 4px 12px;
  padding: 8px;
}
.thumb {
  display: block;
  width: 56px;
  height: 40px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.crumb {
  min-height: var(--ctl-sm);
  padding: 0 8px;
  border-radius: theme('borderRadius.control');
}
.crumb:hover {
  color: theme('colors.camera.text');
}
@media (max-width: 640px) {
  .file-row {
    grid-template-columns: 56px minmax(0, 1fr) auto;
    padding: 12px 0;
  }
  .file-row > :nth-child(1) {
    grid-row: 1 / span 2;
  }
  .file-row > :nth-child(2) {
    grid-column: 2 / -1;
  }
  .file-row > :nth-child(3),
  .file-row > :nth-child(4),
  .file-row > :nth-child(5) {
    font-size: 12px;
    grid-row: 2;
  }
  .file-row > :nth-child(3) {
    grid-column: 2;
  }
  .file-row > :nth-child(4) {
    grid-column: 3;
  }
  .file-row > :nth-child(5) {
    display: none;
  }
  .file-row > :nth-child(6) {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
}
</style>
