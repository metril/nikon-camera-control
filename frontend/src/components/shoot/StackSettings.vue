<script setup>
/** Focus stack settings under the shutter: frames, focus step, and progress while it runs. */
import { computed, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useFocusStore } from '@/stores/focus'
import { useShootStore } from '@/stores/shoot'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import { finite } from './helpers'

const emit = defineEmits(['navigate'])
const camera = useCameraStore()
const focus = useFocusStore()
const shoot = useShootStore()

const directions = [
  { value: 'near_to_far', label: 'Near to far' },
  { value: 'far_to_near', label: 'Far to near' },
]
const locked = computed(() => shoot.stackRunning)
const job = computed(() => shoot.stackJob)
const travel = computed(() =>
  finite(shoot.stack.steps) && finite(shoot.stack.shots)
    ? shoot.stack.steps * Math.max(0, shoot.stack.shots - 1)
    : 0,
)

// the focus position is only readable with a connected camera
watch(
  () => camera.connected,
  (on) => on && focus.fetchStatus().catch(() => {}),
  { immediate: true },
)
</script>

<template>
  <div class="flex flex-col gap-4">
    <template v-if="!locked">
      <div class="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3">
        <UiNumber v-model="shoot.stack.shots" label="Frames" :min="2" :max="200" :step="1" />
        <UiNumber
          v-model="shoot.stack.steps"
          label="Focus step"
          :min="1"
          :max="32767"
          :step="1"
        />
      </div>
      <p class="text-xs text-camera-muted" data-testid="travel">
        Total focus travel: {{ travel }} steps over {{ shoot.stack.shots }} frames
        <span v-if="focus.status?.range">
          (the camera allows {{ focus.status.range.min }} to {{ focus.status.range.max }} per move)</span
        >.
      </p>
      <details class="text-sm">
        <summary class="cursor-pointer text-camera-muted">More options</summary>
        <div class="mt-3 flex flex-col gap-3">
          <UiSegmented
            v-model="shoot.stack.direction"
            size="sm"
            class="w-full"
            :options="directions"
          />
          <UiNumber
            v-model="shoot.stack.settle"
            label="Settle time"
            unit="ms"
            :min="0"
            :max="60000"
            :step="50"
          />
          <UiText v-model="shoot.stack.name" label="Name" placeholder="Optional" :maxlength="40" />
          <UiToggle v-model="shoot.stack.back" label="Return focus to the start" />
        </div>
      </details>
      <p
        v-if="shoot.stackProblem"
        class="text-sm text-camera-danger"
        role="alert"
        data-testid="stack-issue"
      >
        {{ shoot.stackProblem }}
      </p>
    </template>

    <div v-if="job" class="flex flex-col gap-2 text-sm" aria-live="polite" data-testid="stack-job">
      <template v-if="shoot.stackRunning">
        <div class="flex items-baseline justify-between text-xs text-camera-muted">
          <span>Progress</span>
          <b class="font-mono text-base font-medium tabular-nums text-camera-text"
            >{{ shoot.stackDone }} of {{ shoot.stack.shots }}</b
          >
        </div>
        <UiProgress :value="job.progress" :label="job.message || 'Taking frames'" />
      </template>
      <div v-else-if="job.status === 'completed'" class="flex flex-wrap items-center gap-2">
        <UiBadge tone="ok">Done · {{ job.result?.file_count ?? 0 }} files</UiBadge>
        <UiButton
          v-if="job.result?.folder"
          variant="ghost"
          size="sm"
          @click="emit('navigate', 'gallery', job.result.folder)"
        >
          Open in Gallery
        </UiButton>
      </div>
      <UiBadge v-else-if="job.status === 'cancelled'" tone="warn" class="self-start"
        >Cancelled</UiBadge
      >
      <p v-else-if="job.status === 'failed'" class="text-camera-danger" role="alert">
        Failed: {{ job.error }}
      </p>
    </div>
  </div>
</template>
