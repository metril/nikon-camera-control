<script setup>
import { onMounted } from 'vue'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import ConfigForm from '@/components/timelapse/ConfigForm.vue'
import BracketQuick from '@/components/timelapse/BracketQuick.vue'
import BracketSteps from '@/components/timelapse/BracketSteps.vue'
import BracketPresets from '@/components/timelapse/BracketPresets.vue'
import ResolvedPreview from '@/components/timelapse/ResolvedPreview.vue'
import RunPanel from '@/components/timelapse/RunPanel.vue'
import SessionsPanel from '@/components/timelapse/SessionsPanel.vue'
import { draft } from '@/components/timelapse/useDraft'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useTimelapseStore } from '@/stores/timelapse'
import { useToastsStore } from '@/stores/toasts'

const camera = useCameraStore()
const settings = useSettingsStore()
const timelapse = useTimelapseStore()
const toasts = useToastsStore()
const modes = [
  { value: 'none', label: 'None' },
  { value: 'quick', label: 'Quick setup' },
  { value: 'steps', label: 'Advanced steps' },
]
const guarded = (p) => p.catch((e) => toasts.error(e))
onMounted(() => {
  guarded(timelapse.fetchStatus())
  if (camera.connected && !settings.common.length) guarded(settings.fetchCommon())
})
</script>

<template>
  <div class="space-y-4">
    <div
      v-if="!camera.connected"
      class="flex flex-wrap items-center gap-3 rounded border border-amber-700 p-3 text-sm text-amber-300"
    >
      Camera not connected. You can prepare a configuration; it will be validated on start.
      <UiButton size="sm" @click="guarded(camera.connect())">Connect</UiButton>
    </div>
    <div class="grid gap-4 lg:grid-cols-2">
      <div class="space-y-4">
        <ConfigForm />
        <UiCard title="Bracketing">
          <div class="space-y-4">
            <UiSegmented
              :model-value="draft.bracket.mode === 'preset' ? 'quick' : draft.bracket.mode"
              :options="modes"
              @update:model-value="(m) => (draft.bracket.mode = m)"
            />
            <template v-if="draft.bracket.mode !== 'none'">
              <BracketPresets />
              <BracketQuick v-if="draft.bracket.mode === 'quick'" />
              <BracketSteps v-else-if="draft.bracket.mode === 'steps'" />
              <p v-else class="text-sm text-slate-300">Preset: {{ draft.bracket.presetName }}</p>
            </template>
            <ResolvedPreview />
          </div>
        </UiCard>
      </div>
      <div class="space-y-4">
        <RunPanel />
        <SessionsPanel />
      </div>
    </div>
  </div>
</template>
