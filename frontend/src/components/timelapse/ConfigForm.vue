<script setup>
import { computed, watch, onUnmounted } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiText from '@/components/ui/UiText.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useTimelapseStore } from '@/stores/timelapse'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import {
  draft,
  applied,
  preview,
  resultNow,
  fresh,
  localErrors,
  draftKey,
  dirty,
  applyDraft,
  previewDraft,
} from './useDraft'
import { quickShots, formatBytes, formatDuration } from './bracketUtils'

const DEBOUNCE_MS = 600
const timelapse = useTimelapseStore()
const camera = useCameraStore()
const toasts = useToastsStore()

const limitOptions = [
  { value: 'frames', label: 'Number of frames' },
  { value: 'duration', label: 'Duration' },
]
const locked = computed(() => timelapse.isActive)
const result = resultNow
const minInterval = computed(() => result.value?.min_interval_s ?? 0.1)

const errors = computed(() => ({ ...preview.errors, ...applied.errors, ...localErrors.value }))
const shotsPerSet = computed(() => {
  if (result.value && fresh.value) return result.value.estimate.shots_per_set
  const b = draft.bracket
  if (b.mode === 'quick') return quickShots(b.quick) || 1
  if (b.mode === 'steps') return b.steps.length
  return result.value?.estimate.shots_per_set ?? 1
})
const sets = computed(() =>
  draft.limit === 'frames'
    ? draft.totalFrames
    : Math.floor((draft.durationMin * 60) / draft.intervalS) + 1,
)
const fin = (n) => (Number.isFinite(n) && n >= 0 ? n : null)
const estimate = computed(() => {
  const est = result.value?.estimate
  if (est && fresh.value) return est
  const s = fin(sets.value)
  return {
    total_sets: s,
    total_shots: s == null ? null : s * shotsPerSet.value,
    duration_s: s == null ? null : fin((s - 1) * draft.intervalS),
    disk_bytes:
      est && s != null
        ? Math.round((est.disk_bytes / Math.max(1, est.total_shots)) * s * shotsPerSet.value)
        : null,
  }
})
const videoLength = computed(() => {
  const s = estimate.value.total_sets
  return s != null && Number.isFinite(draft.fps) && draft.fps > 0 ? s / draft.fps : null
})
const show = (v, f = String) => (v == null || !Number.isFinite(Number(v)) ? '-' : f(v))

let timer = null
const clear = () => clearTimeout(timer)
async function apply() {
  clear()
  if (!draftKey.value || locked.value) return
  try {
    await applyDraft()
  } catch (e) {
    toasts.error(e)
  }
}
/** The estimate comes from the preview route; the configuration is only saved on Apply/Start. */
async function refreshPreview() {
  if (!draftKey.value || fresh.value) return
  try {
    await previewDraft()
  } catch {
    /* field errors are shown inline from preview.errors */
  }
}
watch(
  draftKey,
  (k) => {
    clear()
    if (k && !fresh.value) timer = setTimeout(refreshPreview, DEBOUNCE_MS)
  },
  { immediate: true },
)
onUnmounted(clear)

const setNum = (key, v) => (draft[key] = v ?? NaN)
</script>

<template>
  <UiCard title="Schedule">
    <template #actions>
      <UiBadge v-if="dirty" tone="warn" aria-live="polite">Unsaved changes</UiBadge>
      <UiBadge v-else-if="result" tone="ok">Applied</UiBadge>
    </template>
    <div class="grid gap-4 sm:grid-cols-2">
      <div class="sm:col-span-2">
        <UiText v-model="draft.name" label="Session name" :maxlength="200" :disabled="locked" />
        <p v-if="errors.name" class="mt-1 text-xs text-red-400" role="alert">{{ errors.name }}</p>
      </div>
      <div>
        <UiNumber
          :model-value="Number.isFinite(draft.intervalS) ? draft.intervalS : null"
          label="Interval"
          unit="s"
          :min="minInterval"
          :step="0.5"
          :disabled="locked"
          @update:model-value="(v) => setNum('intervalS', v)"
        />
        <p v-if="errors.interval_s" class="mt-1 text-xs text-red-400" role="alert">
          {{ errors.interval_s }}
        </p>
        <p v-else class="mt-1 text-xs text-slate-400">Minimum {{ minInterval }} s</p>
      </div>
      <div class="space-y-2">
        <UiSegmented v-model="draft.limit" :options="limitOptions" :disabled="locked" />
        <UiNumber
          v-if="draft.limit === 'frames'"
          :model-value="Number.isFinite(draft.totalFrames) ? draft.totalFrames : null"
          label="Frames"
          :min="1"
          :max="100000"
          :step="1"
          :disabled="locked"
          @update:model-value="(v) => (draft.totalFrames = v == null ? NaN : Math.round(v))"
        />
        <UiNumber
          v-else
          :model-value="Number.isFinite(draft.durationMin) ? draft.durationMin : null"
          label="Duration"
          unit="min"
          :min="0.1"
          :step="1"
          :disabled="locked"
          @update:model-value="(v) => setNum('durationMin', v)"
        />
        <p
          v-if="errors.total_frames || errors.duration_s"
          class="text-xs text-red-400"
          role="alert"
        >
          {{ errors.total_frames || errors.duration_s }}
        </p>
      </div>
    </div>

    <dl class="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4" aria-live="polite">
      <div>
        <dt class="text-xs text-slate-400">Total shots</dt>
        <dd data-test="total-shots">{{ show(estimate.total_shots) }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-400">Shooting time</dt>
        <dd data-test="shoot-time">{{ show(estimate.duration_s, formatDuration) }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-400">Video length</dt>
        <dd data-test="video-length">{{ show(videoLength, formatDuration) }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-400">Disk estimate</dt>
        <dd data-test="disk">{{ show(estimate.disk_bytes, formatBytes) }}</dd>
      </div>
    </dl>
    <div class="mt-3 max-w-[10rem]">
      <UiNumber
        :model-value="Number.isFinite(draft.fps) ? draft.fps : null"
        label="Video fps"
        :min="1"
        :max="120"
        :disabled="locked"
        @update:model-value="(v) => setNum('fps', v)"
      />
    </div>
    <p v-if="errors._" class="mt-3 text-sm text-red-400" role="alert">{{ errors._ }}</p>
    <p v-if="errors.bracketing" class="mt-1 text-xs text-red-400" role="alert">
      {{ errors.bracketing }}
    </p>
    <p v-if="!camera.connected" class="mt-3 text-xs text-slate-400">
      Camera not connected: the configuration will be validated on start.
    </p>
    <div class="mt-4">
      <UiButton
        variant="primary"
        :loading="applied.busy"
        :disabled="locked || !draftKey || !dirty"
        @click="apply"
      >
        Apply configuration
      </UiButton>
    </div>
  </UiCard>
</template>
