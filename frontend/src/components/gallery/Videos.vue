<script setup>
defineOptions({ name: 'GalleryVideos' })
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import { isNoTarget } from '@/api'
import { useStorageStore } from '@/stores/storage'
import { useVideosStore } from '@/stores/videos'
import { useSessionsStore } from '@/stores/sessions'
import { videoCodec } from '@/labels'
import { useToastsStore } from '@/stores/toasts'
import { formatSize, formatDate, formatDuration } from './media'

const videos = useVideosStore()
const sessions = useSessionsStore()
const toasts = useToastsStore()
const storage = useStorageStore()
const noTargetHit = ref(false)
const noStorage = computed(() => storage.noTarget || noTargetHit.value)

const loading = ref(false)
const failed = ref(false)
const playing = ref(null)
const playSrc = ref(null)
const playLoading = ref(false)
const busy = ref(null)
let release = () => {}
let gen = 0

const sessionName = (v) =>
  sessions.items.find((s) => s.id === v.session_id)?.name || 'Time-lapse session'
const key = (v) => `${v.session_id}/${v.name}`
const firstLoad = computed(() => loading.value && !videos.items.length)

async function load() {
  if (storage.noTarget) return // the empty state explains; nothing to list
  loading.value = true
  failed.value = false
  noTargetHit.value = false
  try {
    await videos.fetch()
    // Session names are cosmetic: a failure just falls back to a generic label.
    sessions.fetch({ limit: 100 }).catch(() => {})
  } catch (e) {
    if (isNoTarget(e)) noTargetHit.value = true
    else {
      failed.value = true
      toasts.error(e)
    }
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(
  () => storage.targetId,
  (id) => id && load(),
)

function drop() {
  release()
  release = () => {}
  playSrc.value = null
}
async function play(v) {
  drop()
  playing.value = v
  const mine = ++gen
  playLoading.value = true
  try {
    const r = await videos.acquire(v.session_id, v.name)
    if (mine !== gen) return r.release()
    release = r.release
    playSrc.value = r.url
  } catch (e) {
    toasts.error(e)
  } finally {
    if (mine === gen) playLoading.value = false
  }
}
function close() {
  gen++
  drop()
  playing.value = null
}
onUnmounted(() => {
  gen++
  drop()
})

async function download(v) {
  busy.value = key(v)
  try {
    await videos.download(v.session_id, v.name)
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = null
  }
}
async function remove(v) {
  busy.value = key(v)
  try {
    await videos.remove(v.session_id, v.name)
    toasts.success(`Deleted ${v.name}`)
    if (playing.value && key(playing.value) === key(v)) close()
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <NoTargetNotice v-if="noStorage" data-testid="no-target" />
  <div v-else class="space-y-4">
    <div v-if="firstLoad" class="space-y-2" aria-busy="true">
      <div v-for="n in 4" :key="n" class="h-12 animate-pulse rounded-inner bg-camera-raised" />
    </div>
    <UiEmpty v-else-if="failed && !videos.items.length" title="Could not load videos">
      <template #actions><UiButton @click="load">Retry</UiButton></template>
    </UiEmpty>
    <UiEmpty
      v-else-if="!videos.items.length"
      title="No rendered videos"
      hint="Render a video from a time-lapse session in the Time-lapse tab."
    />
    <div v-else class="text-sm" role="list">
      <div class="video-row eyebrow max-[640px]:!hidden" aria-hidden="true">
        <span>Session</span>
        <span>File</span>
        <span>Size</span>
        <span>Length</span>
        <span>Format</span>
        <span>Date</span>
        <span />
      </div>
      <div
        v-for="v in videos.items"
        :key="key(v)"
        role="listitem"
        class="video-row border-t border-camera-subtle"
      >
        <span class="min-w-0 truncate" :title="v.session_id">{{ sessionName(v) }}</span>
        <button
          type="button"
          class="min-w-0 truncate text-left font-mono text-[13px] text-camera-accent hover:underline"
          :title="v.name"
          @click="play(v)"
        >
          {{ v.name }}
        </button>
        <span class="tabular-nums text-camera-muted">{{ formatSize(v.size) }}</span>
        <span class="tabular-nums text-camera-muted">{{ formatDuration(v.duration_s) }}</span>
        <span class="tabular-nums text-camera-muted"
          >{{ v.fps ? `${v.fps} fps` : '-' }} · {{ v.codec ? videoCodec(v.codec) : '-' }}</span
        >
        <span class="tabular-nums text-camera-muted">{{ formatDate(v.created) }}</span>
        <span class="flex flex-wrap justify-end gap-2 max-[640px]:justify-start">
          <UiButton size="sm" :loading="busy === key(v)" @click="download(v)">
            <UiIcon name="Download" :size="16" />Download
          </UiButton>
          <UiConfirmButton
            size="sm"
            variant="danger"
            :disabled="busy === key(v)"
            @confirm="remove(v)"
          >
            Delete
          </UiConfirmButton>
        </span>
      </div>
    </div>

    <UiModal :open="!!playing" :title="playing?.name || 'Video'" @close="close">
      <video
        v-if="playSrc"
        :src="playSrc"
        controls
        autoplay
        class="max-h-[70vh] w-full rounded-inner bg-black"
        data-testid="player"
      />
      <p v-else-if="playLoading" class="p-6 text-center text-camera-muted">Loading…</p>
    </UiModal>
  </div>
</template>

<style scoped>
.video-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr) 80px 64px 120px 170px auto;
  align-items: center;
  gap: 4px 12px;
  padding: 8px;
}
@media (max-width: 640px) {
  .video-row {
    grid-template-columns: minmax(0, 1fr) auto;
    padding: 12px 0;
    font-size: 12px;
  }
  .video-row > :nth-child(1) {
    grid-column: 1 / -1;
    font-size: 14px;
    font-weight: 500;
  }
  .video-row > :nth-child(2) {
    grid-column: 1 / -1;
  }
  .video-row > :nth-child(3),
  .video-row > :nth-child(5) {
    grid-column: 1;
  }
  .video-row > :nth-child(4),
  .video-row > :nth-child(6) {
    grid-column: 2;
    justify-self: end;
  }
  .video-row > :nth-child(7) {
    grid-column: 1 / -1;
  }
}
html[data-layout='touch'] .video-row {
  font-size: var(--fs-min);
}
</style>
