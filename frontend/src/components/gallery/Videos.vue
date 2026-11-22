<script setup>
defineOptions({ name: 'GalleryVideos' })
import { ref, computed, onMounted, onUnmounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import { useVideosStore } from '@/stores/videos'
import { useToastsStore } from '@/stores/toasts'
import { formatSize, formatDate, formatDuration } from './media'

const videos = useVideosStore()
const toasts = useToastsStore()

const loading = ref(false)
const failed = ref(false)
const playing = ref(null)
const playSrc = ref(null)
const playLoading = ref(false)
const busy = ref(null)
let release = () => {}
let gen = 0

const key = (v) => `${v.session_id}/${v.name}`
const firstLoad = computed(() => loading.value && !videos.items.length)

async function load() {
  loading.value = true
  failed.value = false
  try {
    await videos.fetch()
  } catch (e) {
    failed.value = true
    toasts.error(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

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
  <div class="space-y-4">
    <div v-if="firstLoad" class="space-y-2" aria-busy="true">
      <div v-for="n in 4" :key="n" class="h-12 animate-pulse rounded bg-slate-800" />
    </div>
    <UiEmpty v-else-if="failed && !videos.items.length" title="Could not load videos">
      <template #actions><UiButton @click="load">Retry</UiButton></template>
    </UiEmpty>
    <UiEmpty
      v-else-if="!videos.items.length"
      title="No rendered videos"
      hint="Render a video from a time-lapse session in the Time-lapse tab."
    />
    <div v-else class="overflow-x-auto">
      <table class="w-full text-left text-sm text-slate-300">
        <thead class="text-xs uppercase text-slate-500">
          <tr>
            <th class="p-2">Session</th>
            <th class="p-2">File</th>
            <th class="p-2">Size</th>
            <th class="p-2">Duration</th>
            <th class="p-2">Format</th>
            <th class="p-2">Date</th>
            <th class="p-2"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="v in videos.items" :key="key(v)" class="border-t border-slate-800">
            <td class="p-2">{{ v.session_id }}</td>
            <td class="p-2">
              <button
                type="button"
                class="text-sky-400 hover:underline focus-visible:ring-2 focus-visible:ring-sky-500"
                @click="play(v)"
              >
                {{ v.name }}
              </button>
            </td>
            <td class="p-2">{{ formatSize(v.size) }}</td>
            <td class="p-2">{{ formatDuration(v.duration_s) }}</td>
            <td class="p-2">{{ v.fps ?? '--' }} fps · {{ v.codec || '--' }}</td>
            <td class="p-2">{{ formatDate(v.created) }}</td>
            <td class="whitespace-nowrap p-2 text-right">
              <UiButton size="sm" :loading="busy === key(v)" @click="download(v)"
                >Download</UiButton
              >
              <UiConfirmButton
                size="sm"
                variant="danger"
                class="ml-2"
                :disabled="busy === key(v)"
                @confirm="remove(v)"
              >
                Delete
              </UiConfirmButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <UiModal :open="!!playing" :title="playing?.name || 'Video'" @close="close">
      <video
        v-if="playSrc"
        :src="playSrc"
        controls
        autoplay
        class="max-h-[70vh] w-full rounded bg-black"
        data-testid="player"
      />
      <p v-else-if="playLoading" class="p-6 text-center text-slate-400">Loading…</p>
    </UiModal>
  </div>
</template>
