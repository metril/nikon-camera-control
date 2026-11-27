<script setup>
import { computed, watch, onUnmounted } from 'vue'
import UiText from '@/components/ui/UiText.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import StatGrid from './StatGrid.vue'
import { useTimelapseStore } from '@/stores/timelapse'
import { useCameraStore } from '@/stores/camera'
import {
  draft,
  applied,
  preview,
  resultNow,
  fresh,
  localErrors,
  draftKey,
  previewDraft,
} from './useDraft'
import { quickShots, formatBytes, formatDuration, formatEndsAt } from './bracketUtils'
import { useNow } from './useCountdown'
import { useLayoutMode } from '@/composables/useLayoutMode'

const DEBOUNCE_MS = 600
const timelapse = useTimelapseStore()
const camera = useCameraStore()
const now = useNow()
const { isTouch } = useLayoutMode()

const limitOptions = [
  { value: 'frames', label: 'Frames' },
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
const tooShort = computed(
  () =>
    Number.isFinite(draft.intervalS) && draft.intervalS > 0 && draft.intervalS < minInterval.value,
)
// Running: the end is the time left from now. Otherwise it is now plus the planned duration.
const endsAt = computed(() => {
  const eta = timelapse.status?.timing?.eta_s
  const left = timelapse.isActive && Number.isFinite(eta) ? eta : estimate.value.duration_s
  return left == null ? null : formatEndsAt(now.value, left)
})
const bracketLabel = computed(() => (shotsPerSet.value > 1 ? `${shotsPerSet.value} shots` : 'Off'))
const stats = computed(() => [
  {
    key: 'shots',
    label: 'Total shots',
    value: show(estimate.value.total_shots),
    testid: 'total-shots',
  },
  {
    key: 'time',
    label: 'Shooting time',
    value: show(estimate.value.duration_s, formatDuration),
    testid: 'shoot-time',
  },
  {
    key: 'video',
    label: 'Video length',
    value: show(videoLength.value, formatDuration),
    testid: 'video-length',
  },
  {
    key: 'disk',
    label: 'Disk space',
    value: show(estimate.value.disk_bytes, formatBytes),
    testid: 'disk',
  },
  { key: 'ends', label: 'Ends at', value: endsAt.value ?? '-', testid: 'ends-at' },
  { key: 'bracket', label: 'Bracket', value: bracketLabel.value, testid: 'bracket-stat' },
])

let timer = null
const clear = () => clearTimeout(timer)
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
  <div class="grid gap-4" data-test="config-form">
    <div>
      <UiText v-model="draft.name" label="Session name" :maxlength="200" :disabled="locked" />
      <p v-if="errors.name" class="mt-2 text-xs text-camera-danger" role="alert">
        {{ errors.name }}
      </p>
    </div>
    <div
      class="grid gap-4"
      :class="
        isTouch
          ? 'grid-cols-[repeat(auto-fit,minmax(230px,1fr))]'
          : 'grid-cols-[repeat(auto-fit,minmax(170px,1fr))]'
      "
    >
      <div class="grid content-start gap-2">
        <UiNumber
          :model-value="Number.isFinite(draft.intervalS) ? draft.intervalS : null"
          label="Interval"
          unit="s"
          :min="minInterval"
          :step="0.5"
          :decimals="3"
          :disabled="locked"
          @update:model-value="(v) => setNum('intervalS', v)"
        />
        <p v-if="errors.interval_s" class="text-xs text-camera-danger" role="alert">
          {{ errors.interval_s }}
        </p>
        <p v-else-if="tooShort" class="text-xs text-camera-danger" data-test="too-short">
          Too short. One frame takes at least {{ minInterval }} s with {{ shotsPerSet }}
          {{ shotsPerSet === 1 ? 'shot' : 'shots' }}.
        </p>
        <p v-else class="text-xs text-camera-muted">
          Minimum {{ minInterval }} s<template v-if="shotsPerSet > 1">
            with {{ shotsPerSet }} shots per frame</template
          >
        </p>
      </div>
      <div class="grid content-start gap-2">
        <span class="text-xs font-medium text-camera-muted">Stop after</span>
        <UiSegmented
          v-model="draft.limit"
          class="w-full"
          aria-label="Stop after"
          :options="limitOptions"
          :disabled="locked"
        />
        <UiNumber
          v-if="draft.limit === 'frames'"
          label="Frames"
          class="[&_label]:sr-only"
          :model-value="Number.isFinite(draft.totalFrames) ? draft.totalFrames : null"
          :min="1"
          :max="100000"
          :step="1"
          :disabled="locked"
          @update:model-value="(v) => (draft.totalFrames = v == null ? NaN : Math.round(v))"
        />
        <UiNumber
          v-else
          label="Duration"
          class="[&_label]:sr-only"
          :model-value="Number.isFinite(draft.durationMin) ? draft.durationMin : null"
          unit="min"
          :min="0.1"
          :step="1"
          :decimals="2"
          :disabled="locked"
          @update:model-value="(v) => setNum('durationMin', v)"
        />
        <p
          v-if="errors.total_frames || errors.duration_s"
          class="text-xs text-camera-danger"
          role="alert"
        >
          {{ errors.total_frames || errors.duration_s }}
        </p>
      </div>
      <div class="grid content-start gap-2">
        <UiNumber
          :model-value="Number.isFinite(draft.fps) ? draft.fps : null"
          label="Video frame rate"
          unit="fps"
          :min="1"
          :max="120"
          :decimals="2"
          :disabled="locked"
          @update:model-value="(v) => setNum('fps', v)"
        />
        <p class="text-xs text-camera-muted">Used for the video length estimate.</p>
      </div>
    </div>

    <StatGrid :items="stats" :cols="3" :compact-cols="2" aria-live="polite" />

    <p v-if="errors._" class="text-sm text-camera-danger" role="alert">{{ errors._ }}</p>
    <p v-if="errors.bracketing" class="text-xs text-camera-danger" role="alert">
      {{ errors.bracketing }}
    </p>
    <p v-if="!camera.connected" class="text-xs text-camera-muted">
      Camera not connected: the configuration will be validated on start.
    </p>
    <p v-if="locked" class="text-xs text-camera-muted">
      The schedule is locked while a time-lapse is running.
    </p>
    <p class="text-xs text-camera-muted" data-test="applied-on-start">
      The schedule is applied when you press Start.
    </p>
  </div>
</template>
