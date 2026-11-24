<script setup>
/** Side column: capture mode, shutter, that mode's settings, and the last capture. */
import { computed, ref } from 'vue'
import { useCaptureStore } from '@/stores/capture'
import { CAPTURE_MODES, useShootStore } from '@/stores/shoot'
import { fileKind } from '@/labels'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import BracketSettings from './BracketSettings.vue'
import BulbSettings from './BulbSettings.vue'
import RecordingCard from './RecordingCard.vue'
import SettingsPanel from './SettingsPanel.vue'
import StackSettings from './StackSettings.vue'

const emit = defineEmits(['navigate', 'open-settings'])
const capture = useCaptureStore()
const shoot = useShootStore()

const modes = CAPTURE_MODES.map(({ value, label }) => ({ value, label }))
const modeTitle = computed(() => CAPTURE_MODES.find((m) => m.value === shoot.mode)?.title)
const SETTINGS = { bracket: BracketSettings, bulb: BulbSettings, stack: StackSettings }
const settingsView = computed(() => SETTINGS[shoot.mode] || null)

const result = computed(() => capture.lastCapture)
const first = computed(() => result.value?.files?.[0] || result.value?.camera_files?.[0] || null)
const kinds = computed(() => {
  const list = result.value?.files || []
  return [...new Set(list.map((f) => fileKind(f.kind)))].join(' + ')
})

const cameraSettingsOpen = ref(false)
const recordingOpen = ref(false)
</script>

<template>
  <div class="side">
    <div class="sidecard" :class="{ has: !!settingsView }">
      <UiSegmented
        v-model="shoot.mode"
        class="modes w-full"
        size="sm"
        aria-label="Capture mode"
        :options="modes"
        :disabled="shoot.anyRunning || capture.inFlight"
        :title="modeTitle"
      />
      <div class="shutterwrap">
        <UiButton
          variant="shutter"
          :stop="shoot.stoppable"
          :disabled="!shoot.canPress"
          :aria-label="shoot.label"
          data-testid="capture-btn"
          @click="shoot.press()"
        />
        <span class="slabel tabular-nums" data-testid="shutter-label">{{ shoot.label }}</span>
        <span class="reason" aria-live="polite" data-testid="shutter-reason">
          <NoTargetNotice
            v-if="shoot.noTarget"
            compact
            class="justify-center"
            @open-settings="emit('open-settings')"
          />
          <template v-else-if="shoot.blockedReason && !shoot.stoppable">{{
            shoot.blockedReason
          }}</template>
          <span v-else class="kbdonly"><kbd>Space</kbd></span>
        </span>
      </div>
      <div v-if="settingsView" class="msettings">
        <component :is="settingsView" @navigate="(...a) => emit('navigate', ...a)" />
      </div>
    </div>

    <div class="lastinfo" data-testid="last-capture">
      <template v-if="first">
        <span class="eyebrow">Last capture</span>
        <span class="nm" :title="first.name">{{ first.name }}</span>
        <span class="text-camera-muted">
          {{ kinds || 'On the camera card' }}
          <template v-if="result.files?.length > 1"> · {{ result.files.length }} files</template>
        </span>
      </template>
      <span v-else-if="capture.lastError && !shoot.noTarget" class="text-camera-danger" role="alert">
        {{ capture.lastError.message }}
      </span>
      <span v-else class="text-camera-muted">No captures yet</span>
    </div>

    <div class="tools">
      <UiButton variant="ghost" size="sm" class="-ml-2.5" @click="cameraSettingsOpen = true">
        <UiIcon name="SlidersHorizontal" :size="16" /> All camera settings
      </UiButton>
      <UiButton variant="ghost" size="sm" @click="recordingOpen = true">
        <UiIcon name="Video" :size="16" /> Record video
      </UiButton>
    </div>

    <UiModal
      :open="cameraSettingsOpen"
      title="All camera settings"
      @close="cameraSettingsOpen = false"
    >
      <SettingsPanel />
    </UiModal>
    <UiModal :open="recordingOpen" title="Video recording" @close="recordingOpen = false">
      <RecordingCard />
    </UiModal>
  </div>
</template>

<style scoped>
.side {
  display: grid;
  gap: 12px;
  align-content: start;
  min-width: 0;
}
.sidecard {
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.subtle');
  border-radius: theme('borderRadius.card');
  padding: 16px;
  display: grid;
  gap: 16px;
}
.shutterwrap {
  display: grid;
  justify-items: center;
  gap: 6px;
  padding: 6px 0 2px;
}
.slabel {
  font-weight: 600;
}
.reason {
  min-height: 20px;
  font-size: 12px;
  color: theme('colors.camera.muted');
  text-align: center;
}
.msettings {
  display: grid;
  gap: 16px;
  border-top: 1px solid theme('colors.camera.subtle');
  padding-top: 16px;
}
.lastinfo {
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.subtle');
  border-radius: theme('borderRadius.card');
  padding: 12px 16px;
  display: grid;
  gap: 4px;
  font-size: 13px;
}
.nm {
  font:
    500 13px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tools {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px;
}
kbd {
  font:
    500 11px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  border: 1px solid theme('colors.camera.border');
  border-bottom-width: 2px;
  border-radius: 4px;
  padding: 1px 5px;
  color: theme('colors.camera.text');
  background: theme('colors.camera.raised');
  display: inline-block;
  line-height: 16px;
}
.kbdonly {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
:global(html[data-layout='touch']) .sidecard {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  align-items: center;
  column-gap: 24px;
}
:global(html[data-layout='touch']) .sidecard .modes {
  grid-column: 1 / -1;
}
:global(html[data-layout='touch']) .sidecard:not(.has) .shutterwrap {
  grid-column: 1 / -1;
}
:global(html[data-layout='touch']) .msettings {
  border-top: 0;
  padding-top: 0;
}
@media (max-width: 560px) {
  :global(html[data-layout='touch']) .sidecard {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (min-width: 900px) and (orientation: landscape) {
  :global(html[data-layout='touch']) .sidecard {
    grid-template-columns: minmax(0, 1fr);
  }
  :global(html[data-layout='touch']) .msettings {
    border-top: 1px solid theme('colors.camera.subtle');
    padding-top: 16px;
  }
}
:global(html[data-layout='touch']) .kbdonly {
  display: none;
}
:global(html[data-layout='touch']) .lastinfo {
  display: none;
}
</style>
