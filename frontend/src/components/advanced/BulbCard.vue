<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useBulbStore } from '@/stores/bulb'
import { useFilesStore } from '@/stores/files'
import { useToastsStore } from '@/stores/toasts'
import { useJobsStore } from '@/stores/jobs'
import AdvCard from './AdvCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useJob, finite, fmtDuration } from './helpers'

const bulb = useBulbStore()
const jobs = useJobsStore()
const files = useFilesStore()
const toasts = useToastsStore()

const form = reactive({ seconds: 30, download: true, prefix: '' })
const quick = [
  { label: '30 s', s: 30 },
  { label: '1 min', s: 60 },
  { label: '2 min', s: 120 },
  { label: '5 min', s: 300 },
  { label: '10 min', s: 600 },
]
const jobId = ref(null)
const starting = ref(false)
const stopping = ref(false)
const lookupId = computed(() => jobId.value || bulb.status?.job_id || null)
const { job, running: jobRunning } = useJob(lookupId)
const running = computed(() => jobRunning.value || (!job.value && bulb.active))
const secondsOk = computed(() => finite(form.seconds) && form.seconds >= 1 && form.seconds <= 3600)

// --- client-side countdown, re-anchored whenever the server reports remaining time
const anchor = ref(null) // { remaining, total, at }
const now = ref(Date.now())
let timer = null
const remaining = computed(() =>
  anchor.value ? Math.max(0, anchor.value.remaining - (now.value - anchor.value.at) / 1000) : 0,
)
const total = computed(() => anchor.value?.total || form.seconds)
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
    if (on) timer = setInterval(() => (now.value = Date.now()), 250)
  },
  { immediate: true },
)
onUnmounted(() => clearInterval(timer))

// --- outcome
const SHUTTER_OPEN = /could not (close|confirm)/i
const shutterOpen = computed(
  () =>
    job.value?.status === 'failed' &&
    (job.value.error_code === 'BULB_SHUTTER_OPEN' || SHUTTER_OPEN.test(job.value.error || '')),
)
const warnings = computed(() => {
  const w = [...(job.value?.result?.warnings || [])]
  if (bulb.status?.warning) w.push(bulb.status.warning)
  if (job.value?.warning) w.push(job.value.warning)
  return [...new Set(w)]
})
const resultPath = computed(() => job.value?.result?.files?.[0] || null)
const thumb = ref(null)
watch(
  resultPath,
  async (p) => {
    thumb.value = null
    if (!p) return
    try {
      thumb.value = await files.thumbnailSrc(p, 'medium')
    } catch {
      /* thumbnail is optional */
    }
  },
  { immediate: true },
)

async function start() {
  starting.value = true
  try {
    const j = await bulb.start({
      seconds: form.seconds,
      download: form.download,
      filename_prefix: form.prefix.trim() || null,
    })
    jobId.value = j.id
    jobs.upsert(j)
    reanchor(form.seconds, form.seconds)
  } catch (e) {
    toasts.error(e)
  } finally {
    starting.value = false
  }
}
async function stop() {
  stopping.value = true
  try {
    await jobs.cancel(lookupId.value)
  } catch (e) {
    toasts.error(e)
  } finally {
    stopping.value = false
  }
}

bulb.fetchStatus().catch(() => {})
</script>

<template>
  <AdvCard title="Bulb exposure" subtitle="Long exposures up to 1 hour" feature="bulb">
    <template #default="{ disabled, reason }">
      <div v-if="!running" class="space-y-3">
        <UiNumber
          v-model="form.seconds"
          label="Exposure"
          unit="s"
          :min="1"
          :max="3600"
          :step="1"
          :disabled="disabled"
        />
        <div class="flex flex-wrap gap-2" role="group" aria-label="Quick exposure picks">
          <button
            v-for="q in quick"
            :key="q.s"
            type="button"
            :aria-pressed="form.seconds === q.s"
            :disabled="disabled"
            class="rounded px-2 py-1 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 disabled:opacity-50"
            :class="form.seconds === q.s ? 'bg-sky-600' : 'bg-slate-700 hover:bg-slate-600'"
            @click="form.seconds = q.s"
          >
            {{ q.label }}
          </button>
        </div>
        <UiToggle v-model="form.download" label="Download frame to server" :disabled="disabled" />
        <UiText
          v-model="form.prefix"
          label="Filename prefix"
          :maxlength="80"
          :disabled="disabled"
        />
        <UiButton
          variant="primary"
          :loading="starting"
          :disabled="disabled || !secondsOk"
          :title="reason"
          @click="start"
        >
          Start bulb exposure
        </UiButton>
      </div>

      <div v-else class="space-y-3" aria-live="polite" data-testid="bulb-running">
        <p class="text-center text-4xl font-mono tabular-nums" data-testid="countdown">
          {{ fmtDuration(Math.ceil(remaining)) }}
        </p>
        <UiProgress :value="Math.min(1, Math.max(0, fraction))" label="Exposure progress" />
        <UiButton
          variant="danger"
          class="w-full !py-4 text-lg"
          :loading="stopping"
          :disabled="!lookupId"
          @click="stop"
        >
          Close shutter now
        </UiButton>
      </div>

      <ul
        v-if="warnings.length"
        class="space-y-1 text-sm text-amber-300"
        data-testid="bulb-warnings"
      >
        <li v-for="w in warnings" :key="w">{{ w }}</li>
      </ul>

      <div
        v-if="shutterOpen"
        class="rounded border-2 border-red-500 bg-red-950 p-3 text-sm text-red-100"
        role="alert"
        data-testid="shutter-open"
      >
        <p class="font-bold">THE SHUTTER MAY STILL BE OPEN</p>
        <p>{{ job.error }}</p>
        <p class="mt-1">
          Press the camera's shutter button to close it. If that does not work, switch the camera
          off and on (power-cycle).
        </p>
      </div>
      <p v-else-if="job?.status === 'failed'" class="text-sm text-red-400" role="alert">
        {{ job.error }}
      </p>

      <div
        v-if="job && !running && !shutterOpen && job.status !== 'failed'"
        class="space-y-2 text-sm"
        data-testid="bulb-result"
      >
        <UiBadge :tone="job.status === 'completed' ? 'ok' : 'warn'">
          {{ job.status === 'completed' ? 'Done' : 'Stopped early; frame saved' }}
        </UiBadge>
        <img v-if="thumb" :src="thumb" alt="Bulb exposure result" class="max-h-48 rounded" />
        <p v-else-if="resultPath" class="text-slate-400">{{ resultPath }}</p>
      </div>
    </template>
  </AdvCard>
</template>
