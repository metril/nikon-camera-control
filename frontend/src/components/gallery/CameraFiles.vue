<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { fileKind, leaseOwner } from '@/labels'
import { useCameraStore } from '@/stores/camera'
import { useCameraFilesStore } from '@/stores/cameraFiles'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { formatSize, formatDate } from './media'

const camera = useCameraStore()
const cf = useCameraFilesStore()
const jobs = useJobsStore()
const toasts = useToastsStore()

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
const crumbs = computed(() => {
  const parts = folder.value.split('/').filter(Boolean)
  return parts.map((name, i) => ({ name, path: '/' + parts.slice(0, i + 1).join('/') }))
})
const cards = computed(() => camera.storage?.cards || [])

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
    if (params.folder !== undefined || !subfolders.value.length)
      subfolders.value = (await cf.loadFolders(folder.value))?.folders || []
  } catch (e) {
    failedLoad.value = true
    toasts.error(e)
  }
}
const goFolder = (f) => load({ folder: f, page: 1 })

function init() {
  if (!camera.connected) return
  camera.fetchStorage().catch((e) => toasts.error(e))
  load()
}
onMounted(init)
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

async function downloadOne(f) {
  busyFile.value = f.name
  try {
    await cf.download(f.folder, f.name)
  } catch (e) {
    toasts.error(e)
  } finally {
    busyFile.value = null
  }
}
async function removeOne(f) {
  busyFile.value = f.name
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
      folder: folder.value === '/' ? null : folder.value,
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
        :key="c.label"
        class="rounded-inner border border-camera-border bg-camera-raised px-3 py-2 text-sm text-camera-muted"
      >
        <span class="font-medium text-camera-text">{{ c.label }}</span>
        · <span class="tabular-nums">{{ gb(c.free_kb) }} free of {{ gb(c.capacity_kb) }}</span>
      </div>
    </div>

    <UiCard title="Download all to server">
      <div class="space-y-3">
        <div class="flex flex-wrap gap-x-6 gap-y-3">
          <UiToggle v-model="onlyNew" label="Only new files" :disabled="running" />
          <UiToggle
            v-model="deleteAfter"
            label="Delete from card after download"
            :disabled="running"
          />
        </div>
        <UiAlert v-if="deleteAfter" tone="warn">
          Files are removed from the card once saved to the server.
        </UiAlert>
        <div v-if="running" class="space-y-2" aria-live="polite" data-testid="job-progress">
          <UiProgress :value="job.progress ?? null" :label="job.message || 'Downloading'" />
          <p class="text-sm text-camera-muted">{{ job.message }}</p>
          <UiButton variant="danger" size="sm" :loading="cancelling" @click="cancel"
            >Cancel</UiButton
          >
        </div>
        <div v-else class="flex flex-wrap items-center gap-3">
          <UiButton
            variant="primary"
            :loading="starting"
            :disabled="leased"
            :title="leaseReason"
            @click="startAll"
          >
            Download all
          </UiButton>
          <span v-if="leased" class="text-sm text-camera-warn">{{ leaseReason }}</span>
        </div>
        <p v-if="job?.status === 'failed'" class="text-sm text-camera-danger" role="alert">
          Download failed: {{ job.error || 'unknown error' }}
        </p>
        <p
          v-if="result"
          class="tabular-nums text-sm text-camera-muted"
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
    </UiCard>

    <nav aria-label="Card folder" class="flex flex-wrap items-center gap-1 text-sm">
      <button
        type="button"
        class="rounded-control px-1 hover:text-camera-text"
        :class="crumbs.length ? 'text-camera-muted' : 'text-camera-text'"
        @click="goFolder('/')"
      >
        Card
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
    <div v-if="subfolders.length" class="flex flex-wrap gap-2" data-testid="card-folders">
      <button
        v-for="f in subfolders"
        :key="f.path"
        type="button"
        class="inline-flex h-[var(--ctl-sm)] max-w-full items-center gap-2 rounded-control border border-camera-border bg-camera-raised px-3 text-[13px] hover:bg-camera-hover"
        @click="goFolder(f.path)"
      >
        <UiIcon name="Folder" :size="16" class="text-camera-muted" />
        <span class="truncate">{{ f.name }}</span>
      </button>
    </div>

    <div v-if="cf.loading && !cf.items.length" class="space-y-2" aria-busy="true">
      <div v-for="n in 6" :key="n" class="h-10 animate-pulse rounded-inner bg-camera-raised" />
    </div>
    <UiEmpty v-else-if="failedLoad && !cf.items.length" title="Could not list the card">
      <template #actions><UiButton @click="load()">Retry</UiButton></template>
    </UiEmpty>
    <UiEmpty v-else-if="!cf.items.length" title="No files in this folder" />
    <div v-else class="text-sm" role="list" data-testid="card-files">
      <div class="file-row eyebrow max-[640px]:!hidden" aria-hidden="true">
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
        <span class="flex min-w-0 items-center gap-2">
          <span class="truncate font-mono text-[13px]" :title="f.name">{{ f.name }}</span>
          <UiBadge v-if="f.downloaded" tone="ok">Downloaded</UiBadge>
        </span>
        <span class="tabular-nums text-camera-muted">{{ formatSize(f.size) }}</span>
        <span class="tabular-nums text-camera-muted">{{ formatDate(f.mtime) }}</span>
        <span class="text-camera-muted">{{ fileKind(f.type) }}</span>
        <span class="flex flex-wrap justify-end gap-2 max-[640px]:justify-start">
          <UiButton size="sm" :loading="busyFile === f.name" @click="downloadOne(f)">
            <UiIcon name="Download" :size="16" />Download
          </UiButton>
          <UiConfirmButton
            size="sm"
            variant="danger"
            data-testid="delete-card-file"
            :disabled="leased || busyFile === f.name"
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
/* One row per file; on phones it becomes a card: name, meta line, then actions. */
.file-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 80px 170px 64px auto;
  align-items: center;
  gap: 4px 12px;
  padding: 8px;
}
@media (max-width: 640px) {
  .file-row {
    grid-template-columns: minmax(0, 1fr) auto;
    padding: 12px 0;
  }
  .file-row > :nth-child(2),
  .file-row > :nth-child(3) {
    font-size: 12px;
  }
  .file-row > :nth-child(2) {
    grid-column: 1;
  }
  .file-row > :nth-child(3) {
    grid-column: 2;
    grid-row: 2;
  }
  .file-row > :nth-child(4) {
    grid-column: 2;
    grid-row: 1;
  }
  .file-row > :nth-child(5) {
    grid-column: 1 / -1;
  }
}
</style>
