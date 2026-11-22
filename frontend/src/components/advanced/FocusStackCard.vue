<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useFocusStore } from '@/stores/focus'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import AdvCard from './AdvCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useJob, finite, stackIssue } from './helpers'

const emit = defineEmits(['navigate'])
const focus = useFocusStore()
const jobs = useJobsStore()
const toasts = useToastsStore()

const form = reactive({
  steps: 20,
  shots: 10,
  direction: 'near_to_far',
  settle: 500,
  back: true,
  name: '',
})
const directions = [
  { value: 'near_to_far', label: 'Near → far' },
  { value: 'far_to_near', label: 'Far → near' },
]
const jobId = ref(null)
const starting = ref(false)
const cancelling = ref(false)
const { job, running } = useJob(jobId)

const travel = computed(() =>
  finite(form.steps) && finite(form.shots) ? form.steps * Math.max(0, form.shots - 1) : 0,
)
const issue = computed(() =>
  stackIssue(
    { steps: form.steps, shots: form.shots, direction: form.direction },
    focus.status?.range,
  ),
)
const settleOk = computed(() => finite(form.settle) && form.settle >= 0 && form.settle <= 60000)
const nameOk = computed(() => !form.name || form.name.length <= 40)
const problem = computed(
  () =>
    issue.value ||
    (!settleOk.value && 'Settle must be 0-60000 ms') ||
    (!nameOk.value && 'Name is too long') ||
    '',
)

async function start() {
  starting.value = true
  try {
    const j = await focus.stack({
      steps_per_shot: form.steps,
      shots: form.shots,
      direction: form.direction,
      settle_ms: form.settle,
      return_to_start: form.back,
      name: form.name.trim() || null,
    })
    jobId.value = j.id
    jobs.upsert(j)
  } catch (e) {
    toasts.error(e)
  } finally {
    starting.value = false
  }
}
async function cancel() {
  cancelling.value = true
  try {
    await jobs.cancel(jobId.value)
  } catch (e) {
    toasts.error(e)
  } finally {
    cancelling.value = false
  }
}

const camera = useCameraStore()
// the position is only readable with a connected camera (503 otherwise)
watch(
  () => camera.connected,
  (on) => on && focus.fetchStatus().catch(() => {}),
  { immediate: true },
)
</script>

<template>
  <AdvCard title="Focus stack" subtitle="Step the focus between shots" feature="focus-stack">
    <template #default="{ disabled, reason }">
      <div class="grid grid-cols-2 gap-3">
        <UiNumber
          v-model="form.steps"
          label="Steps per shot"
          :min="1"
          :max="32767"
          :step="1"
          :disabled="disabled || running"
        />
        <UiNumber
          v-model="form.shots"
          label="Shots"
          :min="2"
          :max="200"
          :step="1"
          :disabled="disabled || running"
        />
        <UiNumber
          v-model="form.settle"
          label="Settle"
          unit="ms"
          :min="0"
          :max="60000"
          :step="50"
          :disabled="disabled || running"
        />
        <UiText
          v-model="form.name"
          label="Name"
          placeholder="optional"
          :maxlength="40"
          :disabled="disabled || running"
        />
      </div>
      <UiSegmented v-model="form.direction" :options="directions" :disabled="disabled || running" />
      <UiToggle v-model="form.back" label="Return to start" :disabled="disabled || running" />

      <p class="text-sm text-slate-300" data-testid="travel">
        Total travel: {{ travel }} steps over {{ form.shots }} shots
        <span v-if="focus.status?.range" class="text-slate-400">
          (per-move range {{ focus.status.range.min }} to {{ focus.status.range.max }})
        </span>
      </p>
      <p v-if="problem" class="text-sm text-red-400" role="alert" data-testid="stack-issue">
        {{ problem }}
      </p>

      <div class="flex flex-wrap items-center gap-2">
        <UiButton
          variant="primary"
          :loading="starting"
          :disabled="disabled || running || !!problem"
          :title="reason || problem"
          @click="start"
        >
          Start stack
        </UiButton>
        <UiButton v-if="running" variant="danger" :loading="cancelling" @click="cancel"
          >Cancel</UiButton
        >
      </div>

      <div v-if="job" aria-live="polite" class="space-y-2" data-testid="stack-job">
        <UiProgress :value="job.status === 'completed' ? 1 : job.progress" :label="job.message" />
        <p v-if="running" class="text-sm">{{ job.message }}</p>
        <div
          v-else-if="job.status === 'completed'"
          class="flex flex-wrap items-center gap-2 text-sm"
        >
          <UiBadge tone="ok">Done</UiBadge>
          <span>{{ job.result?.file_count ?? 0 }} files</span>
          <button
            v-if="job.result?.folder"
            type="button"
            class="text-sky-400 underline"
            @click="emit('navigate', 'gallery', job.result.folder)"
          >
            Open {{ job.result.folder }} in Gallery
          </button>
        </div>
        <p v-else-if="job.status === 'cancelled'" class="text-sm text-amber-300">Cancelled</p>
        <p v-else-if="job.status === 'failed'" class="text-sm text-red-400" role="alert">
          Failed: {{ job.error }}
        </p>
      </div>
    </template>
  </AdvCard>
</template>
