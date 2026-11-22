<script setup>
import { ref, onMounted, watch } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiText from '@/components/ui/UiText.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import RenderDialog from './RenderDialog.vue'
import { useSessionsStore } from '@/stores/sessions'
import { useVideosStore } from '@/stores/videos'
import { useTimelapseStore } from '@/stores/timelapse'
import { useToastsStore } from '@/stores/toasts'
import { videoUrl } from '@/api'

const sessions = useSessionsStore()
const videos = useVideosStore()
const timelapse = useTimelapseStore()
const toasts = useToastsStore()
const renaming = ref(null) // {id, name}
const renderFor = ref(null)
const playing = ref(null) // {session_id, name}
const openId = ref(null)

const attempt = async (fn) => {
  try {
    await fn()
  } catch (e) {
    toasts.error(e)
  }
}
const load = () => attempt(() => sessions.fetch({ limit: 10 }))
onMounted(load)
watch(() => timelapse.state, load)

const tone = { completed: 'ok', running: 'info', failed: 'error', interrupted: 'warn' }
const toggle = (s) =>
  attempt(async () => {
    openId.value = openId.value === s.id ? null : s.id
    if (openId.value) await sessions.fetchOne(s.id)
  })
const saveName = () =>
  attempt(async () => {
    const { id, name } = renaming.value
    if (name.trim()) await sessions.rename(id, name.trim())
    renaming.value = null
  })
const removeVideo = (sid, name) =>
  attempt(async () => {
    await videos.remove(sid, name)
    await sessions.fetchOne(sid)
  })
function onRendered() {
  if (openId.value) attempt(() => sessions.fetchOne(openId.value))
  load()
}
const detailVideos = (s) => (sessions.detail?.id === s.id ? sessions.detail.videos : [])
</script>

<template>
  <UiCard title="Recent sessions">
    <UiEmpty v-if="!sessions.items.length" title="No sessions yet" />
    <ul class="space-y-2">
      <li
        v-for="s in sessions.items"
        :key="s.id"
        class="rounded border border-slate-700 p-2"
        data-test="session"
      >
        <div class="flex flex-wrap items-center gap-2">
          <template v-if="renaming?.id === s.id">
            <UiText v-model="renaming.name" label="Name" :maxlength="200" />
            <UiButton size="sm" variant="primary" @click="saveName">Save</UiButton>
            <UiButton size="sm" @click="renaming = null">Cancel</UiButton>
          </template>
          <template v-else>
            <button
              type="button"
              class="flex-1 truncate text-left text-sm"
              :aria-expanded="openId === s.id"
              @click="toggle(s)"
            >
              {{ s.name }}
            </button>
            <UiBadge :tone="tone[s.status] || 'neutral'">{{ s.status }}</UiBadge>
            <span class="text-xs text-slate-400"
              >{{ s.frames_captured }}/{{ s.planned_frames }} frames<template v-if="s.frames_failed"
                >, {{ s.frames_failed }} failed</template
              ></span
            >
          </template>
        </div>
        <div v-if="renaming?.id !== s.id" class="mt-2 flex flex-wrap gap-2">
          <UiButton size="sm" :disabled="!s.frames_captured" @click="renderFor = s"
            >Render video</UiButton
          >
          <UiButton size="sm" @click="renaming = { id: s.id, name: s.name }">Rename</UiButton>
          <UiConfirmButton
            size="sm"
            variant="danger"
            :disabled="['running', 'paused'].includes(s.status)"
            @confirm="attempt(() => sessions.remove(s.id))"
            >Delete</UiConfirmButton
          >
        </div>
        <ul v-if="openId === s.id" class="mt-2 space-y-1 text-sm">
          <li
            v-for="v in detailVideos(s)"
            :key="v.name"
            class="flex flex-wrap items-center gap-2"
            data-test="video"
          >
            <span class="flex-1 truncate">{{ v.name }}</span>
            <UiButton size="sm" @click="playing = { session_id: s.id, name: v.name }"
              >Play</UiButton
            >
            <UiButton size="sm" @click="attempt(() => videos.download(s.id, v.name))"
              >Download</UiButton
            >
            <UiConfirmButton size="sm" variant="danger" @confirm="removeVideo(s.id, v.name)"
              >Delete</UiConfirmButton
            >
          </li>
          <li v-if="!detailVideos(s).length" class="text-xs text-slate-400">No videos yet.</li>
        </ul>
      </li>
    </ul>
    <RenderDialog
      :open="!!renderFor"
      :session="renderFor"
      @close="renderFor = null"
      @done="onRendered"
    />
    <UiModal :open="!!playing" :title="playing?.name || ''" @close="playing = null">
      <video
        v-if="playing"
        :src="videoUrl(playing.session_id, playing.name)"
        controls
        class="w-full"
      />
    </UiModal>
  </UiCard>
</template>
