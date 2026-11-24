<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRecordingStore } from '@/stores/recording'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import AdvCard from './AdvCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { fmtDuration } from './helpers'

const MAX_S = 1799
const recording = useRecordingStore()
const jobs = useJobsStore()
const toasts = useToastsStore()

const form = reactive({ max: null, download: false })
const starting = ref(false)
const stopping = ref(false)
const startError = ref(null)
const maxOk = computed(
  () => form.max === null || (Number.isInteger(form.max) && form.max >= 1 && form.max <= MAX_S),
)

const status = computed(() => recording.status)
const active = computed(() => recording.active)

// Elapsed: re-anchored on every status update, ticks locally while active.
const now = ref(Date.now())
const anchor = ref({ elapsed: 0, at: Date.now() })
let timer = null
watch(
  status,
  (s) => {
    if (s) anchor.value = { elapsed: s.elapsed_s || 0, at: Date.now() }
    now.value = Date.now()
  },
  { immediate: true },
)
const elapsed = computed(() =>
  active.value ? anchor.value.elapsed + (now.value - anchor.value.at) / 1000 : anchor.value.elapsed,
)
watch(
  active,
  (on) => {
    clearInterval(timer)
    timer = null
    if (on) timer = setInterval(() => (now.value = Date.now()), 500)
  },
  { immediate: true },
)
onUnmounted(() => clearInterval(timer))

const REASONS = {
  user: 'Stopped',
  max_seconds: 'Reached the time limit',
  camera_stopped: 'Camera stopped recording',
  camera_reset: 'Camera was reset',
  camera_disconnected: 'Camera disconnected',
  shutdown: 'Server shut down',
}
const clip = computed(() => status.value?.last_clip || recording.lastClip?.clips?.[0] || null)
const dlJob = computed(() => {
  const id = status.value?.job_id || recording.lastClip?.job_id
  return id ? jobs.byId[id] || null : null
})
const movieHint = computed(() => /movie|live ?view|mode/i.test(startError.value?.message || ''))

async function start() {
  starting.value = true
  startError.value = null
  try {
    await recording.start({
      max_seconds: form.max,
      download_after: form.download,
    })
  } catch (e) {
    startError.value = e
    toasts.error(e)
  } finally {
    starting.value = false
  }
}
async function stop() {
  stopping.value = true
  try {
    await recording.stop()
  } catch (e) {
    toasts.error(e)
  } finally {
    stopping.value = false
  }
}

onMounted(() => recording.fetchStatus().catch(() => {}))
</script>

<template>
  <AdvCard title="Video recording" subtitle="Record to the camera card" feature="recording">
    <template #default="{ disabled, reason }">
      <div v-if="!active" class="space-y-3">
        <UiNumber
          v-model="form.max"
          label="Max duration (optional)"
          unit="s"
          :min="1"
          :max="1799"
          :step="1"
          :disabled="disabled"
        />
        <p class="text-xs text-slate-400">Up to 29 min 59 s (1799 s), the camera's clip limit.</p>
        <UiToggle
          v-model="form.download"
          label="Download clip to server when done"
          :disabled="disabled"
        />
        <UiButton
          variant="primary"
          :loading="starting"
          :disabled="disabled || !maxOk"
          :title="reason"
          @click="start"
        >
          Start recording
        </UiButton>
      </div>
      <div v-else class="space-y-3" aria-live="polite">
        <p class="flex items-center gap-2 text-3xl font-mono tabular-nums">
          <span class="h-3 w-3 animate-pulse rounded-full bg-red-500" aria-hidden="true" />
          <span data-testid="elapsed">{{ fmtDuration(elapsed) }}</span>
          <span v-if="status?.max_seconds" class="text-base text-slate-400"
            >/ {{ fmtDuration(status.max_seconds) }}</span
          >
        </p>
        <UiButton variant="danger" :loading="stopping" @click="stop">Stop recording</UiButton>
      </div>

      <p v-if="startError" class="text-sm text-red-400" role="alert" data-testid="start-error">
        {{ startError.message }}
        <span v-if="movieHint" class="block text-slate-300">
          Hint: the camera's live view selector must be set to movie mode.
        </span>
      </p>
      <p v-if="status?.note" class="text-sm text-amber-300" data-testid="rec-note">
        {{ status.note }}
      </p>
      <p v-if="status?.segments > 1" class="text-sm text-slate-300" data-testid="rec-segments">
        {{ status.segments }} movie files so far
      </p>
      <p v-if="status?.warning" class="text-sm text-amber-300" data-testid="rec-warning">
        {{ status.warning }}
      </p>
      <p
        v-if="!active && status?.ended_reason"
        class="text-sm text-slate-300"
        data-testid="ended-reason"
      >
        Ended: {{ REASONS[status.ended_reason] || status.ended_reason }}
      </p>
      <p v-else-if="active && status?.ended_reason" class="text-sm text-amber-300">
        Automatic stop failed ({{ status.ended_reason }}); press Stop to retry.
      </p>

      <div v-if="clip" class="space-y-1 text-sm" data-testid="last-clip">
        <p>
          Last clip: <strong>{{ clip.folder }}/{{ clip.name }}</strong>
          <span v-if="clip.size" class="text-slate-400">
            ({{ (clip.size / 1048576).toFixed(1) }} MB)</span
          >
        </p>
        <div v-if="dlJob" class="space-y-1">
          <UiProgress
            :value="dlJob.status === 'completed' ? 1 : dlJob.progress"
            :label="dlJob.message || 'Downloading clip'"
          />
          <UiBadge v-if="dlJob.status === 'completed'" tone="ok">Downloaded</UiBadge>
          <UiBadge v-else-if="dlJob.status === 'failed'" tone="error"
            >Download failed: {{ dlJob.error }}</UiBadge
          >
        </div>
      </div>
    </template>
  </AdvCard>
</template>
