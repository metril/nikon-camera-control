<script setup>
/** Bracket settings under the shutter: frames, step, an EV scale and the running set. */
import { computed } from 'vue'
import { useShootStore } from '@/stores/shoot'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import EvScale from './EvScale.vue'
import { bracketOffsets } from './helpers'

const emit = defineEmits(['navigate'])
const shoot = useShootStore()

const frames = [3, 5, 7].map((n) => ({ value: n, label: String(n) }))
const steps = [
  { value: 1 / 3, label: '⅓ EV' },
  { value: 2 / 3, label: '⅔ EV' },
  { value: 1, label: '1 EV' },
  { value: 2, label: '2 EV' },
]
const offsets = computed(() => bracketOffsets(shoot.bracket.frames, shoot.bracket.step))
const locked = computed(() => shoot.bracketRunning)
const job = computed(() => shoot.bracketJob)
const shots = computed(() => job.value?.result?.shots || [])
const stepValue = computed({
  get: () => steps.find((s) => Math.abs(s.value - shoot.bracket.step) < 1e-6)?.value ?? 1,
  set: (v) => (shoot.bracket.step = v),
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-col gap-2">
      <span class="text-xs font-medium text-camera-muted">Frames</span>
      <UiSegmented
        v-model="shoot.bracket.frames"
        size="sm"
        class="w-full"
        :options="frames"
        :disabled="locked"
      />
    </div>
    <div class="flex flex-col gap-2">
      <span class="text-xs font-medium text-camera-muted">Step between frames</span>
      <UiSegmented v-model="stepValue" size="sm" class="w-full" :options="steps" :disabled="locked" />
    </div>
    <div class="flex flex-col gap-2">
      <span class="text-xs font-medium text-camera-muted">Exposure of each frame</span>
      <EvScale :offsets="offsets" />
    </div>
    <div v-if="job" class="flex flex-col gap-2 text-sm" aria-live="polite" data-testid="bracket-job">
      <template v-if="shoot.bracketRunning">
        <UiProgress :value="job.progress" :label="job.message || 'Capturing frames'" />
      </template>
      <p v-else-if="job.status === 'failed'" class="text-camera-danger" role="alert">
        {{ job.error }}
      </p>
      <UiBadge v-else-if="job.status === 'cancelled'" tone="warn" class="self-start"
        >Cancelled</UiBadge
      >
      <template v-else-if="job.status === 'completed'">
        <UiBadge tone="ok" class="self-start">Done · {{ shots.length || offsets.length }} frames</UiBadge>
        <UiButton
          v-if="job.result?.directory"
          variant="ghost"
          size="sm"
          class="-ml-2.5 self-start"
          @click="emit('navigate', 'gallery', job.result.directory)"
        >
          Open in Gallery
        </UiButton>
      </template>
    </div>
  </div>
</template>
