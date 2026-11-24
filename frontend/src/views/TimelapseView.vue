<script setup>
import { computed, onMounted } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import ConfigForm from '@/components/timelapse/ConfigForm.vue'
import BracketQuick from '@/components/timelapse/BracketQuick.vue'
import BracketSteps from '@/components/timelapse/BracketSteps.vue'
import BracketPresets from '@/components/timelapse/BracketPresets.vue'
import ResolvedPreview from '@/components/timelapse/ResolvedPreview.vue'
import RunPanel from '@/components/timelapse/RunPanel.vue'
import SessionsPanel from '@/components/timelapse/SessionsPanel.vue'
import { draft, resultNow } from '@/components/timelapse/useDraft'
import { quickShots } from '@/components/timelapse/bracketUtils'
import { options, BRACKET_MODES } from '@/labels'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useTimelapseStore } from '@/stores/timelapse'
import { useToastsStore } from '@/stores/toasts'

const camera = useCameraStore()
const settings = useSettingsStore()
const timelapse = useTimelapseStore()
const toasts = useToastsStore()
const modes = options(BRACKET_MODES)
const locked = computed(() => timelapse.isActive)
const guarded = (p) => p.catch((e) => toasts.error(e))

const shotsPerFrame = computed(() => {
  const b = draft.bracket
  if (b.mode === 'quick') return quickShots(b.quick) || 1
  if (b.mode === 'steps') return b.steps.length
  return resultNow.value?.estimate.shots_per_set ?? 1
})

onMounted(() => {
  guarded(timelapse.fetchStatus())
  if (camera.connected && !settings.common.length) guarded(settings.fetchCommon())
})
</script>

<template>
  <div class="space-y-4">
    <UiAlert v-if="!camera.connected" tone="warn" title="Camera not connected">
      You can prepare a configuration. It is validated when you start.
      <template #action>
        <UiButton size="sm" @click="guarded(camera.connect())">Connect</UiButton>
      </template>
    </UiAlert>
    <div class="tl-grid">
      <div class="grid min-w-0 gap-4">
        <ConfigForm />
        <UiCard title="Bracketing">
          <template #actions>
            <span class="text-[12.5px] text-camera-muted tabular-nums">
              {{ shotsPerFrame > 1 ? `${shotsPerFrame} shots per frame` : 'One shot per frame' }}
            </span>
          </template>
          <div class="grid gap-4">
            <UiSegmented
              v-model="draft.bracket.mode"
              class="w-full"
              aria-label="Bracketing"
              :options="modes"
              :disabled="locked"
            />
            <p v-if="draft.bracket.mode === 'none'" class="text-[13px] text-camera-muted">
              Each frame is one shot at the current camera settings.
            </p>
            <BracketQuick v-else-if="draft.bracket.mode === 'quick'" :disabled="locked" />
            <BracketSteps v-else-if="draft.bracket.mode === 'steps'" :disabled="locked" />
            <BracketPresets v-else :disabled="locked" />
            <p v-if="locked" class="text-xs text-camera-muted">
              Bracketing is locked while a time-lapse is running.
            </p>
            <ResolvedPreview />
            <BracketPresets
              v-if="['quick', 'steps'].includes(draft.bracket.mode)"
              variant="save"
              :disabled="locked"
            />
          </div>
        </UiCard>
      </div>
      <div class="tl-run grid min-w-0 gap-4">
        <RunPanel />
      </div>
    </div>
    <SessionsPanel />
  </div>
</template>

<style scoped>
.tl-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 16px;
  align-items: start;
}
.tl-run {
  position: sticky;
  top: 72px;
}
@media (max-width: 1000px) {
  .tl-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .tl-run {
    position: static;
  }
}
</style>
