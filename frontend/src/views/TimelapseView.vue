<script setup>
import { computed, onMounted, ref } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import SectionTabs from '@/components/timelapse/SectionTabs.vue'
import ConfigForm from '@/components/timelapse/ConfigForm.vue'
import BracketQuick from '@/components/timelapse/BracketQuick.vue'
import BracketSteps from '@/components/timelapse/BracketSteps.vue'
import BracketPresets from '@/components/timelapse/BracketPresets.vue'
import ResolvedPreview from '@/components/timelapse/ResolvedPreview.vue'
import RunPanel from '@/components/timelapse/RunPanel.vue'
import SessionsPanel from '@/components/timelapse/SessionsPanel.vue'
import { draft, resultNow } from '@/components/timelapse/useDraft'
import { quickShots } from '@/components/timelapse/bracketUtils'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { options, BRACKET_MODES } from '@/labels'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useTimelapseStore } from '@/stores/timelapse'
import { useToastsStore } from '@/stores/toasts'

const camera = useCameraStore()
const settings = useSettingsStore()
const timelapse = useTimelapseStore()
const toasts = useToastsStore()
const { isTouch } = useLayoutMode()
const modes = options(BRACKET_MODES)
// Touch layout: two tab strips. Both panels of a strip stay mounted so nothing resets.
const scheduleTab = ref('timing')
const runTab = ref('run')
const scheduleTabs = [
  { id: 'timing', label: 'Timing' },
  { id: 'bracket', label: 'Bracket' },
]
const runTabs = [
  { id: 'run', label: 'Run' },
  { id: 'sessions', label: 'Sessions' },
]
const showSchedule = (id) => !isTouch.value || scheduleTab.value === id
const showRun = (id) => !isTouch.value || runTab.value === id
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
  <div class="tl-root" data-test="timelapse">
    <UiAlert v-if="!camera.connected" tone="warn" title="Camera not connected" class="tl-alert">
      You can prepare a configuration. It is validated when you start.
      <template #action>
        <UiButton size="sm" @click="guarded(camera.connect())">Connect</UiButton>
      </template>
    </UiAlert>
    <div class="tl-grid" :class="{ 'tl-touch': isTouch }">
      <div class="tl-col" data-test="schedule-col">
        <SectionTabs
          v-if="isTouch"
          v-model="scheduleTab"
          name="schedule"
          label="Schedule"
          :tabs="scheduleTabs"
        />
        <section
          v-show="showSchedule('timing')"
          id="tl-schedule-panel-timing"
          class="tl-card tl-fixed"
          aria-label="Schedule"
          :role="isTouch ? 'tabpanel' : undefined"
        >
          <h2 v-if="!isTouch" class="tl-title">Schedule</h2>
          <div class="tl-body scroll-panel"><ConfigForm /></div>
        </section>
        <section
          v-show="showSchedule('bracket')"
          id="tl-schedule-panel-bracket"
          class="tl-card tl-grow"
          aria-label="Bracket"
          :role="isTouch ? 'tabpanel' : undefined"
        >
          <div v-if="!isTouch" class="tl-title">
            <h2>Bracketing</h2>
            <span class="text-[12.5px] font-normal text-camera-muted tabular-nums">
              {{ shotsPerFrame > 1 ? `${shotsPerFrame} shots per frame` : 'One shot per frame' }}
            </span>
          </div>
          <div class="tl-body scroll-panel">
            <div class="grid gap-4">
              <UiSegmented
                v-model="draft.bracket.mode"
                class="w-full"
                aria-label="Bracketing"
                :options="modes"
                :disabled="locked"
              />
              <p v-if="isTouch" class="text-[12.5px] text-camera-muted tabular-nums">
                {{ shotsPerFrame > 1 ? `${shotsPerFrame} shots per frame` : 'One shot per frame' }}
              </p>
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
          </div>
        </section>
      </div>
      <div class="tl-col" data-test="run-col">
        <SectionTabs v-if="isTouch" v-model="runTab" name="run" label="Run" :tabs="runTabs" />
        <section
          v-show="showRun('run')"
          id="tl-run-panel-run"
          class="tl-card tl-run"
          aria-label="Run"
          :role="isTouch ? 'tabpanel' : undefined"
        >
          <h2 v-if="!isTouch" class="tl-title">Run</h2>
          <div class="tl-body"><RunPanel /></div>
        </section>
        <section
          v-show="showRun('sessions')"
          id="tl-run-panel-sessions"
          class="tl-card tl-sessions"
          aria-label="Sessions"
          :role="isTouch ? 'tabpanel' : undefined"
        >
          <h2 v-if="!isTouch" class="tl-title">Sessions</h2>
          <div class="tl-body scroll-panel"><SessionsPanel /></div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tl-root {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.tl-alert {
  flex: none;
}
.tl-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.tl-col {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tl-card {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid theme('colors.camera.border');
  border-radius: 12px;
  background: theme('colors.camera.surface');
}
.tl-fixed {
  flex: none;
  max-height: 60%;
}
.tl-grow,
.tl-sessions {
  flex: 1 1 0;
}
.tl-run {
  flex: 3 1 0;
}
.tl-sessions {
  flex: 2 1 0;
  min-height: 140px;
}
.tl-title {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 600;
  border-bottom: 1px solid theme('colors.camera.border');
}
.tl-title h2 {
  margin: 0;
  font-size: inherit;
  font-weight: inherit;
}
.tl-body {
  flex: 1;
  min-height: 0;
  padding: 16px;
}
/* Touch: one card per column; the tab strip is its header and the panels fill the rest. */
.tl-touch .tl-col {
  gap: 0;
  border: 1px solid theme('colors.camera.border');
  border-radius: 12px;
  background: theme('colors.camera.surface');
  overflow: hidden;
}
.tl-touch .tl-card {
  flex: 1 1 0;
  max-height: none;
  min-height: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
@media (max-width: 899px) {
  /* Phones: stacked columns; this is the one place the page body scrolls, inside the frame. */
  .tl-root {
    overflow: auto;
  }
  .tl-grid {
    flex: none;
    grid-template-columns: minmax(0, 1fr);
  }
  .tl-col {
    min-height: 420px;
  }
}
</style>
