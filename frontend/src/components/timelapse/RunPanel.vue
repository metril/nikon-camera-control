<script setup>
import { ref, computed, watch } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import { useTimelapseStore } from '@/stores/timelapse'
import { useCameraStore } from '@/stores/camera'
import { useFilesStore } from '@/stores/files'
import { useToastsStore } from '@/stores/toasts'
import { draft, applied, resultNow, draftKey, dirty, applyDraft } from './useDraft'
import { useNow } from './useCountdown'
import { formatDuration } from './bracketUtils'

const timelapse = useTimelapseStore()
const camera = useCameraStore()
const files = useFilesStore()
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
const planned = computed(() => status.value?.counters?.frames_planned ?? 0)
const fraction = computed(() =>
  planned.value > 0 ? Math.min(1, (counters.value.frames_done ?? 0) / planned.value) : null,
)
const tone = { running: 'ok', paused: 'warn', failed: 'error', stopping: 'warn', completed: 'info' }

const isActive = computed(() => timelapse.isActive)
const startBlock = computed(() => {
  if (!camera.connected) return 'Camera not connected'
  if (camera.leasedBy && camera.leasedBy !== 'timelapse') return `Busy: ${camera.leasedBy}`
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
</script>

<template>
  <UiCard title="Run">
    <template #actions>
      <UiBadge :tone="tone[state] || 'neutral'" data-test="state">{{ state }}</UiBadge>
    </template>
    <div class="flex flex-wrap gap-2">
      <UiButton
        v-if="!isActive"
        variant="primary"
        :loading="busy === 'start'"
        :disabled="!!startBlock"
        @click="start"
      >
        Start
      </UiButton>
      <UiButton
        v-if="state === 'running'"
        :loading="busy === 'pause'"
        @click="run('pause', timelapse.pause)"
      >
        Pause
      </UiButton>
      <UiButton
        v-if="state === 'paused'"
        variant="primary"
        :loading="busy === 'resume'"
        @click="run('resume', timelapse.resume)"
      >
        Resume
      </UiButton>
      <UiConfirmButton
        v-if="isActive"
        variant="danger"
        :loading="busy === 'stop' || state === 'stopping'"
        @confirm="run('stop', timelapse.stop)"
      >
        Stop
      </UiConfirmButton>
    </div>
    <p v-if="!isActive && startBlock" class="mt-2 text-xs text-amber-400" data-test="start-block">
      {{ startBlock }}
    </p>

    <div v-if="isActive || counters.frames_done" class="mt-4 space-y-2">
      <UiProgress :value="fraction" :label="`${counters.frames_done ?? 0} of ${planned} frames`" />
      <dl class="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
        <div>
          <dt class="text-xs text-slate-400">Sets</dt>
          <dd>{{ counters.sets_done ?? 0 }}</dd>
        </div>
        <div>
          <dt class="text-xs text-slate-400">Failures</dt>
          <dd>
            {{ counters.failures ?? 0 }} ({{ counters.consecutive_failures ?? 0 }}/{{
              failureBudget
            }}
            in a row)
          </dd>
        </div>
        <div>
          <dt class="text-xs text-slate-400">Elapsed</dt>
          <dd>{{ formatDuration(status?.timing?.elapsed_s) }}</dd>
        </div>
        <div>
          <dt class="text-xs text-slate-400">ETA</dt>
          <dd>{{ eta == null ? '-' : formatDuration(eta) }}</dd>
        </div>
        <div>
          <dt class="text-xs text-slate-400">Next shot</dt>
          <dd data-test="next">{{ nextIn == null ? '-' : `${nextIn} s` }}</dd>
        </div>
      </dl>
    </div>
    <img v-if="thumb" :src="thumb" alt="Last captured frame" class="mt-3 max-h-40 rounded" />

    <div class="mt-3 space-y-2" aria-live="polite">
      <p
        v-if="status?.paused_reason === 'camera_disconnected'"
        class="text-sm text-amber-400"
        data-test="disconnected"
      >
        Camera disconnected. The time-lapse will resume automatically.
      </p>
      <p v-else-if="state === 'paused'" class="text-sm text-slate-300">Paused by user.</p>
      <div
        v-if="warning"
        class="rounded border border-amber-600 p-2 text-sm text-amber-300"
        data-test="warning"
      >
        {{ warning.message || warning.code }}
        <UiButton
          v-if="warning.code === 'interval_too_short' && suggested"
          size="sm"
          class="ml-2"
          @click="useSuggested"
        >
          Use {{ suggested }} s
        </UiButton>
        <UiButton
          size="sm"
          variant="ghost"
          aria-label="Dismiss warning"
          @click="timelapse.warning = null"
          >×</UiButton
        >
      </div>
      <p
        v-if="state === 'failed' || status?.error"
        class="text-sm text-red-400"
        role="alert"
        data-test="error"
      >
        {{ status?.error || 'The time-lapse failed.' }}
      </p>
    </div>
  </UiCard>
</template>
