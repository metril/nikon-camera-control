<script setup>
import { ref, computed, watch } from 'vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import { formatDuration } from './bracketUtils'
import { useSessionsStore } from '@/stores/sessions'
import {
  options,
  jobStatus,
  VIDEO_CODECS,
  VIDEO_QUALITIES,
  VIDEO_RESOLUTIONS,
  ENCODER_PRESETS,
  BRACKET_FRAMES,
} from '@/labels'
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
const sessions = useSessionsStore()

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

const codecs = options(VIDEO_CODECS)
const qualities = options(VIDEO_QUALITIES)
const presets = [{ value: '', label: 'Default' }, ...options(ENCODER_PRESETS)]
// config.video.codec (ffmpeg names) -> render request codec enum
const CODEC_MAP = { libx264: 'h264', libx265: 'h265', 'libvpx-vp9': 'vp9' }
const resolutions = options(VIDEO_RESOLUTIONS)
const frames = options(BRACKET_FRAMES)

/** Shots per frame in the session's bracketing; 1 when it was not bracketed. */
function setSize(b) {
  if (!b || b.mode === 'none') return 1
  if (b.mode === 'steps') return b.steps?.length || 1
  if (b.mode === 'quick') {
    const lens = ['exposure', 'iso', 'aperture', 'shutter']
      .map((k) => b[k]?.length ?? 0)
      .filter(Boolean)
    if (!lens.length) return 1
    return b.combine_mode === 'paired' ? Math.max(...lens) : lens.reduce((x, y) => x + y, 0)
  }
  return 1
}
const bracketing = computed(() =>
  props.session && sessions.detail?.id === props.session.id
    ? sessions.detail.config?.bracketing
    : null,
)
const bracketed = computed(() => !!bracketing.value && bracketing.value.mode !== 'none')
const frameCount = computed(() =>
  Math.round((props.session?.frames_captured ?? 0) / setSize(bracketing.value)),
)
const videoLength = computed(() =>
  frameCount.value && form.value.fps > 0 ? frameCount.value / form.value.fps : null,
)

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
    if (props.session) Promise.resolve(sessions.fetchOne(props.session.id)).catch(() => {})
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
    <div v-if="!job" class="grid grid-cols-2 gap-4 max-[560px]:grid-cols-1">
      <div class="grid content-start gap-2">
        <UiNumber
          :model-value="Number.isFinite(form.fps) ? form.fps : null"
          label="Frame rate"
          unit="fps"
          :min="1"
          :max="120"
          :decimals="2"
          @update:model-value="(v) => num('fps', v)"
        />
        <p class="text-xs text-camera-muted tabular-nums" data-test="render-length">
          <template v-if="videoLength != null">
            {{ frameCount.toLocaleString() }} frames make about {{ formatDuration(videoLength) }} of
            video.
          </template>
          <template v-else>Video length depends on the frame rate.</template>
        </p>
      </div>
      <UiSelect v-model="form.resolution" label="Resolution" :options="resolutions" />
      <UiSelect v-model="form.codec" label="Codec" :options="codecs" />
      <UiSelect v-model="form.quality" label="Quality" :options="qualities" />
      <div class="grid content-start gap-2">
        <UiNumber
          :model-value="Number.isFinite(form.crf) ? form.crf : null"
          label="CRF"
          :min="0"
          :max="51"
          :disabled="!!form.quality"
          @update:model-value="(v) => num('crf', v)"
        />
        <p v-if="form.quality" class="text-xs text-camera-muted">
          Set by the quality choice. Pick Default quality to change it.
        </p>
      </div>
      <UiSelect v-model="form.preset" label="Encoder preset" :options="presets" />
      <UiSelect
        v-if="bracketed"
        v-model="form.bracket_frame"
        label="Bracket frame"
        :options="frames"
      />
      <div class="flex items-end pb-2.5">
        <UiToggle v-model="form.deflicker" label="Deflicker" />
      </div>
      <div class="col-span-2 max-[560px]:col-span-1">
        <UiText v-model="form.output_name" label="File name (optional)" :maxlength="120" />
      </div>
    </div>
    <div v-else class="grid gap-3" aria-live="polite">
      <UiProgress :value="job.progress" :label="job.message || jobStatus(job.status)" />
      <UiAlert v-if="job.status === 'completed'" tone="ok">Video rendered.</UiAlert>
      <UiAlert v-if="job.error" tone="danger">{{ job.error }}</UiAlert>
    </div>
    <template #footer>
      <UiButton v-if="running" variant="danger" @click="cancel">Cancel render</UiButton>
      <UiButton v-else-if="job" @click="emit('close')">Close</UiButton>
      <template v-else>
        <UiButton variant="ghost" @click="emit('close')">Cancel</UiButton>
        <UiButton variant="primary" :loading="busy" :disabled="!session" @click="submit"
          >Render</UiButton
        >
      </template>
    </template>
  </UiModal>
</template>
