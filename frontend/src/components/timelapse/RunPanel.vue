<script setup>
import { ref, computed, watch } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import StatGrid from './StatGrid.vue'
import { timelapseState, timelapsePauseReason, timelapseWarning, leaseOwner } from '@/labels'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import { useTimelapseStore } from '@/stores/timelapse'
import { useCameraStore } from '@/stores/camera'
import { useFilesStore } from '@/stores/files'
import { useStorageStore } from '@/stores/storage'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import { useToastsStore } from '@/stores/toasts'
import { draft, applied, resultNow, draftKey, dirty, applyDraft } from './useDraft'
import { useNow } from './useCountdown'
import { formatDuration } from './bracketUtils'

const timelapse = useTimelapseStore()
const camera = useCameraStore()
const files = useFilesStore()
const storage = useStorageStore()
const toasts = useToastsStore()
const now = useNow()
const busy = ref('')

const status = computed(() => timelapse.status)
const state = computed(() => timelapse.state)
const counters = computed(() => ({
  ...(status.value?.counters || {}),
  ...pickCounters(timelapse.progress),
}))
function pickCounters(p) {
  if (!p) return {}
  const out = {}
  for (const k of ['frames_done', 'sets_done', 'failures', 'consecutive_failures'])
    if (p[k] !== undefined) out[k] = p[k]
  return out
}
// The server counts shots; the card speaks in frames (one frame = one bracket set of shots).
const perFrame = computed(
  () =>
    resultNow.value?.estimate?.shots_per_set ||
    status.value?.config?.bracketing?.steps?.length ||
    1,
)
const plannedFrames = computed(() =>
  Math.round((status.value?.counters?.frames_planned ?? 0) / perFrame.value),
)
const doneFrames = computed(() => counters.value.sets_done ?? 0)
const fraction = computed(() =>
  plannedFrames.value > 0
    ? Math.min(1, doneFrames.value / plannedFrames.value)
    : state.value === 'running' || state.value === 'configured' || timelapse.isActive
      ? null
      : 0,
)
const tone = {
  running: 'accent',
  paused: 'warn',
  failed: 'danger',
  stopping: 'warn',
  completed: 'ok',
  interrupted: 'warn',
}
const confirmStop = ref(false)
watch(state, () => (confirmStop.value = false))

const isActive = computed(() => timelapse.isActive)
const startBlock = computed(() => {
  if (!camera.connected) return 'Camera not connected'
  if (storage.noTarget) return 'No storage target'
  if (camera.leasedBy && camera.leasedBy !== 'timelapse')
    return `Busy: ${leaseOwner(camera.leasedBy)}`
  if (!draftKey.value) return 'Fix the configuration first'
  return ''
})

const nextIn = computed(() => {
  const t = status.value?.timing?.next_shot_at
  if (!t || state.value !== 'running') return null
  return Math.max(0, Math.ceil((Date.parse(t) - now.value) / 1000))
})
const failureBudget = computed(() => status.value?.failure_budget ?? 5)
const eta = computed(() => status.value?.timing?.eta_s)
const dash = (v, f) => (v == null || !Number.isFinite(v) ? '—' : f(v))

const warning = computed(() => timelapse.warning)
const suggested = computed(() => {
  const v = status.value?.measured_set_duration_s || resultNow.value?.min_interval_s
  return Number.isFinite(v) && v > 0 ? Math.ceil(v * 10) / 10 : null
})

async function run(name, fn) {
  busy.value = name
  try {
    await fn()
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = ''
  }
}
const start = () =>
  run('start', async () => {
    if (dirty.value || !applied.result) await applyDraft()
    await timelapse.start()
  })
const useSuggested = () => (draft.intervalS = suggested.value)

const thumb = ref(null)
const lastFile = computed(() => {
  const lf = status.value?.last_frame
  if (!lf?.files?.length || !status.value.session_id) return null
  const f = lf.files.find((n) => /\.jpe?g$/i.test(n)) || lf.files[0]
  return `sessions/${status.value.session_id}/${f}`
})
watch(
  lastFile,
  async (p, _old, onCleanup) => {
    thumb.value = null
    let stale = false
    let release = () => {}
    onCleanup(() => {
      stale = true
      release()
    })
    if (!p) return
    try {
      const h = await files.acquireThumbnail(p, 400)
      if (stale) return h.release()
      release = h.release
      thumb.value = h.url
    } catch {
      thumb.value = null
    }
  },
  { immediate: true },
)
watch(
  () => timelapse.lastFrame,
  () => timelapse.fetchStatus().catch(() => {}),
)

const stats = computed(() => {
  const c = counters.value
  const started = isActive.value || c.frames_done
  return [
    { key: 'shots', label: 'Shots', value: (c.frames_done ?? 0).toLocaleString() },
    {
      key: 'failures',
      label: 'Failures',
      value: String(c.failures ?? 0),
      note: c.consecutive_failures
        ? `(${c.consecutive_failures}/${failureBudget.value} in a row)`
        : '',
    },
    { key: 'per', label: 'Per frame', value: String(perFrame.value) },
    {
      key: 'elapsed',
      label: 'Elapsed',
      value: started ? dash(status.value?.timing?.elapsed_s, formatDuration) : '—',
    },
    {
      key: 'left',
      label: 'Time left',
      value: isActive.value ? dash(eta.value, formatDuration) : '—',
    },
    {
      key: 'next',
      label: 'Next shot',
      value: nextIn.value == null ? '—' : `in ${nextIn.value} s`,
      testid: 'next',
    },
  ]
})
</script>

<template>
  <UiCard title="Run">
    <template #actions>
      <UiBadge :tone="tone[state] || 'neutral'" data-test="state">{{
        timelapseState(state)
      }}</UiBadge>
    </template>
    <div class="grid gap-4">
      <div class="aspect-[3/2] overflow-hidden rounded-inner border border-camera-subtle bg-black">
        <img
          v-if="thumb"
          :src="thumb"
          alt="Latest time-lapse frame"
          class="block h-full w-full object-contain"
        />
        <div
          v-else
          class="flex h-full flex-col items-center justify-center gap-2 text-center text-[13px] text-camera-muted"
        >
          <UiIcon name="ImageOff" :size="24" class="text-camera-faint" />
          The latest frame shows here.
        </div>
      </div>

      <UiProgress :value="fraction" :label="`${doneFrames} of ${plannedFrames} frames`" />
      <StatGrid :items="stats" :cols="3" />

      <div v-if="status?.paused_reason === 'camera_disconnected'" data-test="disconnected">
        <UiAlert tone="warn" :title="timelapsePauseReason(status.paused_reason)">
          The time-lapse will resume automatically when the camera is back.
        </UiAlert>
      </div>
      <UiAlert
        v-else-if="state === 'paused' && !confirmStop"
        tone="info"
        :title="timelapsePauseReason(status?.paused_reason || 'user')"
      >
        Resume to continue from frame {{ doneFrames + 1 }}.
      </UiAlert>
      <UiAlert
        v-if="warning"
        tone="warn"
        dismissible
        :title="timelapseWarning(warning.code)"
        data-test="warning"
        @dismiss="timelapse.warning = null"
      >
        <template v-if="warning.message && warning.message !== timelapseWarning(warning.code)">
          {{ warning.message }}
        </template>
        <template v-if="warning.code === 'interval_too_short' && suggested" #action>
          <UiButton size="sm" @click="useSuggested">Use {{ suggested }} s</UiButton>
        </template>
      </UiAlert>
      <UiAlert
        v-if="state === 'failed' || status?.error"
        tone="danger"
        title="The time-lapse failed"
        data-test="error"
      >
        {{ status?.error || 'The time-lapse failed.' }}
      </UiAlert>

      <template v-if="confirmStop && isActive">
        <UiAlert tone="warn" title="Stop the time-lapse?"> Frames taken so far are kept. </UiAlert>
        <div class="flex flex-wrap gap-2">
          <UiButton
            variant="danger"
            :loading="busy === 'stop' || state === 'stopping'"
            @click="run('stop', timelapse.stop)"
          >
            Stop now
          </UiButton>
          <UiButton variant="ghost" @click="confirmStop = false">
            {{ state === 'paused' ? 'Keep paused' : 'Keep running' }}
          </UiButton>
        </div>
      </template>
      <div v-else-if="isActive" class="flex flex-wrap gap-2">
        <UiButton
          v-if="state === 'running'"
          :loading="busy === 'pause'"
          @click="run('pause', timelapse.pause)"
        >
          <UiIcon name="Pause" :size="16" />Pause
        </UiButton>
        <UiButton
          v-if="state === 'paused'"
          variant="primary"
          :loading="busy === 'resume'"
          @click="run('resume', timelapse.resume)"
        >
          <UiIcon name="Play" :size="16" />Resume
        </UiButton>
        <UiButton :loading="state === 'stopping'" @click="confirmStop = true">
          <UiIcon name="Square" :size="16" />Stop
        </UiButton>
      </div>
      <div v-else class="grid gap-2">
        <UiButton
          variant="primary"
          class="w-full"
          :loading="busy === 'start'"
          :disabled="!!startBlock"
          @click="start"
        >
          <UiIcon name="Play" :size="16" />Start time-lapse
        </UiButton>
        <NoTargetNotice v-if="camera.connected && storage.noTarget" compact />
        <p v-else-if="startBlock" class="text-xs text-camera-warn" data-test="start-block">
          {{ startBlock }}
        </p>
      </div>
    </div>
  </UiCard>
</template>
