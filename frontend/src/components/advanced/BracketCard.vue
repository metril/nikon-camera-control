<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { usePresetsStore } from '@/stores/presets'
import { useCaptureStore } from '@/stores/capture'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import AdvCard from './AdvCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useJob, evSeries } from './helpers'

const emit = defineEmits(['navigate'])
const presets = usePresetsStore()
const capture = useCaptureStore()
const jobs = useJobsStore()
const toasts = useToastsStore()

const form = reactive({ source: 'ev', presetId: '', shots: 5, ev: 1, download: true, prefix: '' })
const sources = [
  { value: 'ev', label: 'EV series' },
  { value: 'preset', label: 'Preset' },
]
const shotOptions = [3, 5, 7].map((n) => ({ value: n, label: `${n} shots` }))
const evOptions = [1, 2, 3].map((n) => ({ value: n, label: `${n} EV step` }))

const bracketPresets = computed(() => presets.bracketPresets)
const presetOptions = computed(() =>
  bracketPresets.value.map((p) => ({ value: p.id, label: p.name })),
)

const series = computed(() => evSeries(form.shots, form.ev))
const bracketing = computed(() =>
  form.source === 'preset'
    ? { mode: 'preset', preset: form.presetId }
    : { mode: 'quick', exposure: series.value, combine_mode: 'sequence' },
)
const canStart = computed(() => form.source === 'ev' || !!form.presetId)

const steps = ref([])
const previewing = ref(false)
async function preview() {
  previewing.value = true
  try {
    steps.value = (await presets.apply(form.presetId)).steps || []
  } catch (e) {
    steps.value = []
    toasts.error(e)
  } finally {
    previewing.value = false
  }
}

const jobId = ref(null)
const starting = ref(false)
const cancelling = ref(false)
const { job, running } = useJob(jobId)
const shots = computed(() => job.value?.result?.shots || [])

async function start() {
  starting.value = true
  try {
    const j = await capture.bracket({
      bracketing: bracketing.value,
      download: form.download,
      filename_prefix: form.prefix.trim() || null,
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

onMounted(() => {
  if (!presets.items.length) presets.fetch().catch(() => {})
})
</script>

<template>
  <AdvCard title="Bracketed shot" subtitle="One bracket set, right now" feature="bracket">
    <template #default="{ disabled, reason }">
      <UiSegmented v-model="form.source" :options="sources" :disabled="disabled || running" />

      <div v-if="form.source === 'ev'" class="space-y-2">
        <UiSegmented v-model="form.shots" :options="shotOptions" :disabled="disabled || running" />
        <UiSegmented v-model="form.ev" :options="evOptions" :disabled="disabled || running" />
        <p class="text-sm text-slate-300" data-testid="ev-series">
          EV: {{ series.map((v) => (Number(v) > 0 ? `+${v}` : v)).join(', ') }}
        </p>
      </div>
      <div v-else class="space-y-2">
        <UiSelect
          v-model="form.presetId"
          label="Bracket preset"
          :options="presetOptions"
          :disabled="disabled || running"
        />
        <UiButton
          size="sm"
          :loading="previewing"
          :disabled="disabled || !form.presetId"
          @click="preview"
        >
          Show resolved steps
        </UiButton>
        <ol v-if="steps.length" class="list-decimal pl-5 text-sm" data-testid="resolved-steps">
          <li v-for="s in steps" :key="s.index">
            {{ s.label || 'Step' }}
            <span class="text-slate-400">{{
              Object.entries(s.settings)
                .map(([k, v]) => `${k}=${v}`)
                .join(', ')
            }}</span>
          </li>
        </ol>
        <p v-if="!presetOptions.length" class="text-sm text-slate-400">No bracket presets yet.</p>
      </div>

      <UiToggle
        v-model="form.download"
        label="Download frames to server"
        :disabled="disabled || running"
      />
      <UiText
        v-model="form.prefix"
        label="Filename prefix"
        :maxlength="80"
        :disabled="disabled || running"
      />

      <div class="flex flex-wrap gap-2">
        <UiButton
          variant="primary"
          :loading="starting"
          :disabled="disabled || running || !canStart"
          :title="reason"
          @click="start"
        >
          Capture bracket
        </UiButton>
        <UiButton v-if="running" variant="danger" :loading="cancelling" @click="cancel"
          >Cancel</UiButton
        >
      </div>

      <div v-if="job" class="space-y-2 text-sm" aria-live="polite" data-testid="bracket-job">
        <UiProgress :value="job.status === 'completed' ? 1 : job.progress" :label="job.message" />
        <p v-if="running">{{ job.message }}</p>
        <p v-else-if="job.status === 'failed'" class="text-red-400" role="alert">{{ job.error }}</p>
        <UiBadge v-else-if="job.status === 'cancelled'" tone="warn">Cancelled</UiBadge>
        <template v-else-if="job.status === 'completed'">
          <UiBadge tone="ok">Done</UiBadge>
          <ul class="space-y-1" data-testid="bracket-shots">
            <li v-for="s in shots" :key="s.index">
              <strong>{{ s.label || `Step ${s.index + 1}` }}</strong>
              <span class="text-slate-400">
                {{ [...s.files, ...(s.camera_files || [])].join(', ') || 'no files' }}</span
              >
            </li>
          </ul>
          <button
            v-if="job.result?.directory"
            type="button"
            class="text-sky-400 underline"
            @click="emit('navigate', 'gallery', job.result.directory)"
          >
            Open in Gallery
          </button>
        </template>
      </div>
    </template>
  </AdvCard>
</template>
