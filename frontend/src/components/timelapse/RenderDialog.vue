<script setup>
import { ref, computed, watch } from 'vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import { useVideosStore } from '@/stores/videos'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useConfigStore } from '@/stores/config'

const props = defineProps({ open: Boolean, session: { type: Object, default: null } })
const emit = defineEmits(['close', 'done'])
const videos = useVideosStore()
const jobs = useJobsStore()
const toasts = useToastsStore()
const config = useConfigStore()

const form = ref({
  fps: 24,
  codec: 'h264',
  quality: '',
  crf: 20,
  preset: '',
  resolution: 'source',
  bracket_frame: 'middle',
  deflicker: false,
  output_name: '',
})
const jobId = ref(null)
const busy = ref(false)
const job = computed(() => (jobId.value ? jobs.byId[jobId.value] : null))
const running = computed(() => ['queued', 'pending', 'running'].includes(job.value?.status))

const opts = (a) => a.map((v) => ({ value: v, label: v || 'default' }))
const codecs = opts(['h264', 'h265', 'prores', 'vp9'])
const qualities = opts(['', 'low', 'medium', 'high'])
const presets = opts([
  '',
  'ultrafast',
  'superfast',
  'veryfast',
  'faster',
  'fast',
  'medium',
  'slow',
  'slower',
  'veryslow',
])
// config.video.codec (ffmpeg names) -> render request codec enum
const CODEC_MAP = { libx264: 'h264', libx265: 'h265', 'libvpx-vp9': 'vp9' }
const resolutions = opts(['source', '2160p', '1080p', '720p'])
const frames = opts(['middle', 'first', 'last'])

function payload() {
  const f = form.value
  const out = {
    codec: f.codec,
    resolution: f.resolution,
    bracket_frame: f.bracket_frame,
    deflicker: f.deflicker,
  }
  if (Number.isFinite(f.fps) && f.fps > 0) out.fps = f.fps
  if (f.quality) out.quality = f.quality
  else if (Number.isFinite(f.crf)) out.crf = f.crf
  if (f.preset) out.preset = f.preset
  if (f.output_name.trim()) out.output_name = f.output_name.trim()
  return out
}

async function submit() {
  busy.value = true
  try {
    const j = await videos.render(props.session.id, payload())
    jobs.upsert(j)
    jobId.value = j.id
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = false
  }
}
async function cancel() {
  try {
    await jobs.cancel(jobId.value)
  } catch (e) {
    toasts.error(e)
  }
}
watch(
  () => job.value?.status,
  (s) => s === 'completed' && emit('done'),
)
/** Defaults come from Settings > video.* (fetched if not loaded yet). */
async function applyVideoDefaults() {
  if (!config.config) await Promise.resolve(config.fetch?.()).catch(() => {})
  const v = config.config?.video
  if (!v || !props.open) return
  const f = form.value
  if (CODEC_MAP[v.codec]) f.codec = CODEC_MAP[v.codec]
  if (Number.isFinite(v.fps)) f.fps = v.fps
  if (Number.isFinite(v.crf)) f.crf = v.crf
  f.quality = ''
  if (presets.some((p) => p.value === v.preset)) f.preset = v.preset
}
watch(
  () => props.open,
  (o) => {
    if (!o) return
    if (!running.value) jobId.value = null
    applyVideoDefaults()
  },
  { immediate: true },
)
const num = (key, v) => (form.value[key] = v ?? NaN)
</script>

<template>
  <UiModal
    :open="open"
    :title="`Render video${session ? `: ${session.name}` : ''}`"
    @close="emit('close')"
  >
    <div v-if="!job" class="grid gap-3 sm:grid-cols-2">
      <UiNumber
        :model-value="Number.isFinite(form.fps) ? form.fps : null"
        label="Frame rate"
        unit="fps"
        :min="1"
        :max="120"
        @update:model-value="(v) => num('fps', v)"
      />
      <UiSelect v-model="form.codec" label="Codec" :options="codecs" />
      <UiSelect v-model="form.quality" label="Quality" :options="qualities" />
      <UiNumber
        v-if="!form.quality"
        :model-value="Number.isFinite(form.crf) ? form.crf : null"
        label="CRF"
        :min="0"
        :max="51"
        @update:model-value="(v) => num('crf', v)"
      />
      <UiSelect v-model="form.preset" label="Encoder preset" :options="presets" />
      <UiSelect v-model="form.resolution" label="Resolution" :options="resolutions" />
      <UiSelect v-model="form.bracket_frame" label="Bracket frame" :options="frames" />
      <UiToggle v-model="form.deflicker" label="Deflicker" />
      <UiText
        v-model="form.output_name"
        label="Name (optional)"
        :maxlength="120"
        class="sm:col-span-2"
      />
    </div>
    <div v-else class="space-y-2" aria-live="polite">
      <UiProgress :value="job.progress" :label="job.message || job.status" />
      <p v-if="job.status === 'completed'" class="text-sm text-emerald-400">Video rendered.</p>
      <p v-if="job.error" class="text-sm text-red-400" role="alert">{{ job.error }}</p>
    </div>
    <template #footer>
      <UiButton v-if="running" variant="danger" @click="cancel">Cancel render</UiButton>
      <UiButton v-else-if="job" @click="emit('close')">Close</UiButton>
      <template v-else>
        <UiButton @click="emit('close')">Cancel</UiButton>
        <UiButton variant="primary" :loading="busy" :disabled="!session" @click="submit"
          >Render</UiButton
        >
      </template>
    </template>
  </UiModal>
</template>
