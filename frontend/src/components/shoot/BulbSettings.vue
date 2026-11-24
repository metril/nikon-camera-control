<script setup>
/** Bulb settings under the shutter: exposure time and quick times, then a countdown while open. */
import { computed, onUnmounted, ref, watch } from 'vue'
import { useBulbStore } from '@/stores/bulb'
import { useFilesStore } from '@/stores/files'
import { useShootStore } from '@/stores/shoot'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import { finite, fmtDuration, useJob } from './helpers'

const bulb = useBulbStore()
const files = useFilesStore()
const shoot = useShootStore()

const quick = [
  { label: '10 s', value: 10 },
  { label: '30 s', value: 30 },
  { label: '1 min', value: 60 },
  { label: '2 min', value: 120 },
]

const lookupId = computed(() => bulb.jobId || bulb.status?.job_id || null)
const { job } = useJob(lookupId)
const running = computed(() => shoot.bulbRunning)

// --- client-side countdown, re-anchored whenever the server reports remaining time
const anchor = ref(null) // { remaining, total, at }
const now = ref(Date.now())
let timer = null
const remaining = computed(() =>
  anchor.value ? Math.max(0, anchor.value.remaining - (now.value - anchor.value.at) / 1000) : 0,
)
const total = computed(() => anchor.value?.total || shoot.bulbForm.seconds)
const fraction = computed(() => (total.value ? 1 - remaining.value / total.value : 0))
function reanchor(rem, tot) {
  if (!finite(rem)) return
  anchor.value = { remaining: rem, total: tot ?? anchor.value?.total ?? rem, at: Date.now() }
  now.value = Date.now()
}
watch(
  () => job.value?.message,
  (m) => {
    const hit = /(\d+(?:\.\d+)?)\s*s remaining/.exec(m || '')
    if (hit) reanchor(parseFloat(hit[1]))
  },
)
watch(
  () => bulb.status,
  (s) => s?.active && reanchor(s.remaining_s, s.seconds),
  { immediate: true },
)
watch(
  running,
  (on) => {
    clearInterval(timer)
    timer = null
    if (on) {
      if (!anchor.value || anchor.value.remaining <= 0)
        reanchor(shoot.bulbForm.seconds, shoot.bulbForm.seconds)
      timer = setInterval(() => (now.value = Date.now()), 250)
    }
  },
  { immediate: true },
)
onUnmounted(() => clearInterval(timer))

// --- outcome
// Contract with the backend: the shutter-open failure is job.error_code === 'BULB_SHUTTER_OPEN'
// and warnings are job.result.warnings.
const shutterOpen = computed(
  () => job.value?.status === 'failed' && job.value.error_code === 'BULB_SHUTTER_OPEN',
)
const warnings = computed(() => [...new Set(job.value?.result?.warnings || [])])
const resultPath = computed(() => job.value?.result?.files?.[0] || null)
const thumb = ref(null)
watch(
  resultPath,
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
      /* thumbnail is optional */
    }
  },
  { immediate: true },
)
bulb.fetchStatus().catch(() => {})
</script>

<template>
  <div class="flex flex-col gap-4">
    <template v-if="!running">
      <UiNumber
        v-model="shoot.bulbForm.seconds"
        label="Exposure time"
        unit="s"
        :min="1"
        :max="3600"
        :step="1"
      />
      <UiSegmented
        v-model="shoot.bulbForm.seconds"
        size="sm"
        class="w-full"
        aria-label="Quick times"
        :options="quick.map((q) => ({ value: q.value, label: q.label }))"
      />
      <p class="text-xs text-camera-muted">
        Needs the mode dial on M. The shutter speed is set to Bulb for you.
      </p>
    </template>
    <div v-else class="flex flex-col gap-2" aria-live="polite" data-testid="bulb-running">
      <div class="flex items-baseline justify-between text-xs text-camera-muted">
        <span>Time left</span>
        <b
          class="font-mono text-base font-medium tabular-nums text-camera-text"
          data-testid="countdown"
          >{{ fmtDuration(Math.ceil(remaining)) }}</b
        >
      </div>
      <UiProgress :value="Math.min(1, Math.max(0, fraction))" label="Exposure progress" />
      <p class="text-xs text-camera-muted">
        Keep the camera still. The photo is saved when the shutter closes.
      </p>
    </div>

    <UiAlert v-if="warnings.length" tone="warn" data-testid="bulb-warnings">
      <ul>
        <li v-for="w in warnings" :key="w">{{ w }}</li>
      </ul>
    </UiAlert>
    <UiAlert
      v-if="shutterOpen"
      tone="danger"
      title="The shutter may still be open"
      data-testid="shutter-open"
    >
      <p>{{ job.error }}</p>
      <p class="mt-1">
        Press the camera's shutter button to close it. If that does not work, switch the camera off
        and on.
      </p>
    </UiAlert>
    <p v-else-if="job?.status === 'failed'" class="text-sm text-camera-danger" role="alert">
      {{ job.error }}
    </p>
    <div
      v-if="job && !running && !shutterOpen && job.status !== 'failed'"
      class="flex flex-col gap-2 text-sm"
      data-testid="bulb-result"
    >
      <UiBadge :tone="job.status === 'completed' ? 'ok' : 'warn'" class="self-start">
        {{ job.status === 'completed' ? 'Done' : 'Stopped early; frame saved' }}
      </UiBadge>
      <img
        v-if="thumb"
        :src="thumb"
        alt="Bulb exposure result"
        class="max-h-48 rounded-inner object-contain"
      />
    </div>
  </div>
</template>
