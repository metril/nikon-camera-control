<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRecordingStore } from '@/stores/recording'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useCameraStore } from '@/stores/camera'
import { leaseOwner } from '@/labels'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { fmtDuration } from './helpers'

const MAX_S = 1799
const camera = useCameraStore()
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

const reason = computed(() => {
  if (!camera.connected) return 'Camera not connected'
  if (camera.leasedBy && camera.leasedBy !== 'recording')
    return `Busy: ${leaseOwner(camera.leasedBy)}`
  return ''
})
const disabled = computed(() => !!reason.value)
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
  <div class="flex flex-col gap-4">
    <p
      v-if="reason"
      id="rec-reason"
      class="text-sm text-camera-warn"
      role="status"
      data-testid="busy"
    >
      {{ reason }}
    </p>
    <div v-if="!active" class="flex flex-col gap-4">
      <UiNumber
        v-model="form.max"
        label="Longest recording (optional)"
        unit="s"
        :min="1"
        :max="1799"
        :step="1"
        :disabled="disabled"
      />
      <p class="text-xs text-camera-muted">Up to 29 min 59 s, the camera's clip limit.</p>
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
        :aria-describedby="reason ? 'rec-reason' : maxOk ? undefined : 'rec-max'"
        @click="start"
      >
        Start recording
      </UiButton>
      <p v-if="!maxOk" id="rec-max" class="-mt-2 text-xs text-camera-warn">
        Enter a whole number of seconds from 1 to 1799.
      </p>
    </div>
    <div v-else class="flex flex-col gap-4" aria-live="polite">
      <p class="flex items-center gap-2 text-3xl font-mono tabular-nums">
        <span class="h-3 w-3 animate-pulse rounded-full bg-camera-danger-fill" aria-hidden="true" />
        <span data-testid="elapsed">{{ fmtDuration(elapsed) }}</span>
        <span v-if="status?.max_seconds" class="text-base text-camera-muted"
          >/ {{ fmtDuration(status.max_seconds) }}</span
        >
      </p>
      <UiButton variant="danger" :loading="stopping" @click="stop">Stop recording</UiButton>
    </div>

    <p v-if="startError" class="text-sm text-camera-danger" role="alert" data-testid="start-error">
      {{ startError.message }}
      <span v-if="movieHint" class="block text-camera-muted">
        The camera's live view selector must be set to movie mode.
      </span>
    </p>
    <p v-if="status?.note" class="text-sm text-camera-warn" data-testid="rec-note">
      {{ status.note }}
    </p>
    <p v-if="status?.segments > 1" class="text-sm text-camera-muted" data-testid="rec-segments">
      {{ status.segments }} movie files so far
    </p>
    <p v-if="status?.warning" class="text-sm text-camera-warn" data-testid="rec-warning">
      {{ status.warning }}
    </p>
    <p
      v-if="!active && status?.ended_reason"
      class="text-sm text-camera-muted"
      data-testid="ended-reason"
    >
      Ended: {{ REASONS[status.ended_reason] || 'Stopped' }}
    </p>
    <p v-else-if="active && status?.ended_reason" class="text-sm text-camera-warn">
      Automatic stop failed. Press Stop to try again.
    </p>

    <div v-if="clip" class="space-y-1 text-sm" data-testid="last-clip">
      <p>
        Last clip: <strong>{{ clip.folder }}/{{ clip.name }}</strong>
        <span v-if="clip.size" class="text-camera-muted">
          ({{ (clip.size / 1048576).toFixed(1) }} MB)</span
        >
      </p>
      <div v-if="dlJob" class="space-y-1">
        <UiProgress
          :value="dlJob.status === 'completed' ? 1 : dlJob.progress"
          :label="dlJob.message || 'Downloading the clip'"
        />
        <UiBadge v-if="dlJob.status === 'completed'" tone="ok">Downloaded</UiBadge>
        <UiBadge v-else-if="dlJob.status === 'failed'" tone="danger"
          >Download failed: {{ dlJob.error }}</UiBadge
        >
      </div>
    </div>
  </div>
</template>
