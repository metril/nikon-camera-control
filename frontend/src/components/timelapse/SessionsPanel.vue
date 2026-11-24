<script setup>
import { ref, nextTick, onMounted, onUnmounted, watch } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiText from '@/components/ui/UiText.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import RenderDialog from './RenderDialog.vue'
import { useSessionsStore } from '@/stores/sessions'
import { useVideosStore } from '@/stores/videos'
import { useTimelapseStore } from '@/stores/timelapse'
import { isNoTarget } from '@/api'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import { timelapseState, videoCodec } from '@/labels'
import { formatDate, formatDuration } from '@/components/gallery/media'

const sessions = useSessionsStore()
const videos = useVideosStore()
const timelapse = useTimelapseStore()
const toasts = useToastsStore()
const storage = useStorageStore()
const renaming = ref(null) // {id, name}
const confirming = ref(null) // 'session:<id>' or 'video:<id>/<name>'
const renderFor = ref(null)
const playing = ref(null) // {session_id, name}
const openId = ref(null)
const playSrc = ref(null)
let releasePlay = () => {}
let playGen = 0

function dropPlay() {
  releasePlay()
  releasePlay = () => {}
  playSrc.value = null
}
// The video URL may need the API key header, so it comes from the store (blob URL when keyed).
watch(playing, async (p) => {
  dropPlay()
  const mine = ++playGen
  if (!p) return
  try {
    const r = await videos.acquire(p.session_id, p.name)
    if (mine !== playGen) return r.release()
    releasePlay = r.release
    playSrc.value = r.url
  } catch (e) {
    toasts.error(e)
  }
})
onUnmounted(() => {
  playGen++
  dropPlay()
})

const attempt = async (fn) => {
  try {
    await fn()
  } catch (e) {
    if (!isNoTarget(e)) toasts.error(e)
  }
}
const load = () => {
  if (!storage.targetId) return undefined // no sessions can exist yet: show the empty state
  return attempt(() => sessions.fetch({ limit: 10 }))
}
onMounted(load)
watch(() => timelapse.state, load)
watch(() => storage.targetId, load)

const tone = {
  completed: 'ok',
  running: 'accent',
  paused: 'warn',
  failed: 'danger',
  interrupted: 'warn',
  stopped: 'warn',
}
const isLive = (s) => ['running', 'paused'].includes(s.status)
const toggle = (s) =>
  attempt(async () => {
    openId.value = openId.value === s.id ? null : s.id
    if (openId.value) await sessions.fetchOne(s.id)
  })
function startRename(s) {
  renaming.value = { id: s.id, name: s.name }
  nextTick(() => document.querySelector('[data-rename] input')?.focus())
}
const saveName = () =>
  attempt(async () => {
    const { id, name } = renaming.value
    if (name.trim()) await sessions.rename(id, name.trim())
    renaming.value = null
  })
const removeSession = (s) =>
  attempt(async () => {
    confirming.value = null
    await sessions.remove(s.id)
  })
const removeVideo = (sid, name) =>
  attempt(async () => {
    confirming.value = null
    await videos.remove(sid, name)
    await sessions.fetchOne(sid)
  })
function onRendered() {
  if (openId.value) attempt(() => sessions.fetchOne(openId.value))
  load()
}
const detailVideos = (s) => (sessions.detail?.id === s.id ? sessions.detail.videos : [])
const vKey = (sid, name) => `video:${sid}/${name}`
const sKey = (s) => `session:${s.id}`
const plural = (n, one, many) => `${n.toLocaleString()} ${n === 1 ? one : many}`
const reason = (s) =>
  isLive(s)
    ? 'Stop the time-lapse before deleting it.'
    : !s.frames_captured
      ? 'No shots to render.'
      : ''
</script>

<template>
  <UiCard title="Sessions">
    <UiEmpty
      v-if="!sessions.items.length"
      title="No sessions yet"
      hint="Finished and stopped time-lapses appear here."
    />
    <ul v-else class="m-0 grid list-none p-0">
      <li
        v-for="s in sessions.items"
        :key="s.id"
        class="border-b border-camera-subtle last:border-b-0"
        data-test="session"
      >
        <div class="flex min-h-[var(--ctl)] flex-wrap items-center gap-x-3 gap-y-2 py-2.5">
          <div class="grid min-w-0 flex-1 basis-[200px] gap-px">
            <div v-if="renaming?.id === s.id" data-rename class="flex flex-wrap items-center gap-2">
              <div class="min-w-[160px] max-w-[300px] flex-1">
                <UiText
                  v-model="renaming.name"
                  label="Session name"
                  :maxlength="200"
                  @keydown.enter.prevent="saveName"
                  @keydown.esc="renaming = null"
                />
              </div>
              <UiButton size="sm" variant="primary" @click="saveName">Save</UiButton>
              <UiButton size="sm" variant="ghost" @click="renaming = null">Cancel</UiButton>
            </div>
            <template v-else>
              <button
                type="button"
                class="flex min-w-0 items-center gap-1.5 text-left text-sm font-semibold"
                :aria-expanded="openId === s.id"
                :title="s.name"
                @click="toggle(s)"
              >
                <UiIcon :name="openId === s.id ? 'ChevronDown' : 'ChevronRight'" :size="16" />
                <span class="truncate">{{ s.name }}</span>
              </button>
              <span class="truncate pl-[22px] text-xs tabular-nums text-camera-muted">
                {{ s.frames_captured.toLocaleString() }} of
                {{ s.planned_frames.toLocaleString() }} shots
                <template v-if="s.frames_failed"> · {{ s.frames_failed }} failed</template>
                <template v-if="s.video_count">
                  · {{ plural(s.video_count, 'video', 'videos') }}</template
                >
                · {{ formatDate(s.created) }}
              </span>
            </template>
          </div>
          <UiBadge :tone="tone[s.status] || 'neutral'">{{ timelapseState(s.status) }}</UiBadge>
          <div
            v-if="renaming?.id !== s.id"
            class="flex flex-wrap items-center gap-1 max-[640px]:basis-full"
          >
            <UiButton size="sm" :disabled="!s.frames_captured" @click="renderFor = s">
              <UiIcon name="Video" :size="16" />Render video
            </UiButton>
            <UiButton size="sm" variant="ghost" @click="startRename(s)">Rename</UiButton>
            <template v-if="confirming === sKey(s)">
              <UiButton size="sm" variant="danger" @click="removeSession(s)"
                >Delete session</UiButton
              >
              <UiButton size="sm" variant="ghost" @click="confirming = null">Keep</UiButton>
            </template>
            <UiButton
              v-else
              size="sm"
              variant="ghost"
              :disabled="isLive(s)"
              @click="confirming = sKey(s)"
            >
              Delete
            </UiButton>
          </div>
        </div>
        <p v-if="reason(s)" class="-mt-1 pb-2 text-xs text-camera-muted">{{ reason(s) }}</p>

        <div
          v-if="openId === s.id"
          class="mb-2.5 ml-1 grid gap-0.5 border-l-2 border-camera-subtle pb-2.5 pl-3"
        >
          <div
            v-for="v in detailVideos(s)"
            :key="v.name"
            class="flex min-h-[var(--ctl-sm)] flex-wrap items-center gap-x-2.5 gap-y-1 text-[13px]"
            data-test="video"
          >
            <UiIcon name="Video" :size="16" class="text-camera-muted" />
            <span class="min-w-0 truncate font-mono text-[12.5px]" :title="v.name">{{
              v.name
            }}</span>
            <span class="text-xs tabular-nums text-camera-muted">
              {{ formatDuration(v.duration_s) }} · {{ v.codec ? videoCodec(v.codec) : '-' }}
            </span>
            <span class="flex-1" />
            <div class="flex flex-wrap items-center gap-1 max-[640px]:basis-full">
              <UiButton
                size="sm"
                variant="ghost"
                @click="playing = { session_id: s.id, name: v.name }"
              >
                <UiIcon name="Play" :size="16" />Play
              </UiButton>
              <UiButton
                size="sm"
                variant="ghost"
                @click="attempt(() => videos.download(s.id, v.name))"
              >
                <UiIcon name="Download" :size="16" />Download
              </UiButton>
              <template v-if="confirming === vKey(s.id, v.name)">
                <UiButton size="sm" variant="danger" @click="removeVideo(s.id, v.name)">
                  Delete video
                </UiButton>
                <UiButton size="sm" variant="ghost" @click="confirming = null">Keep</UiButton>
              </template>
              <UiButton v-else size="sm" variant="ghost" @click="confirming = vKey(s.id, v.name)">
                <UiIcon name="Trash2" :size="16" />Delete
              </UiButton>
            </div>
          </div>
          <p v-if="!detailVideos(s).length" class="text-xs text-camera-muted">No videos yet.</p>
        </div>
      </li>
    </ul>
    <RenderDialog
      :open="!!renderFor"
      :session="renderFor"
      @close="renderFor = null"
      @done="onRendered"
    />
    <UiModal :open="!!playing" :title="playing?.name || ''" @close="playing = null">
      <video v-if="playSrc" :src="playSrc" controls class="w-full rounded-inner bg-black" />
    </UiModal>
  </UiCard>
</template>
