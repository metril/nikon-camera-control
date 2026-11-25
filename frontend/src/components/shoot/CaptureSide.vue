<script setup>
/** Side column: capture mode, shutter, that mode's settings, and the last capture. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import { useCaptureStore } from '@/stores/capture'
import { CAPTURE_MODES, useShootStore } from '@/stores/shoot'
import { useKeyboardHints } from '@/composables/useKeyboardHints'
import { fileKind } from '@/labels'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import BracketSettings from './BracketSettings.vue'
import BulbSettings from './BulbSettings.vue'
import RecordingCard from './RecordingCard.vue'
import SettingsPanel from './SettingsPanel.vue'
import StackSettings from './StackSettings.vue'

const emit = defineEmits(['navigate', 'open-settings'])
const capture = useCaptureStore()
const shoot = useShootStore()
const config = useConfigStore()
const storage = useStorageStore()
const toasts = useToastsStore()
// When the column scrolls on its own (touch landscape), fade its bottom edge while more is below
const root = ref(null)
const moreBelow = ref(false)
function measure() {
  const el = root.value
  moreBelow.value = !!el && el.scrollTop + el.clientHeight < el.scrollHeight - 2
}
let ro = null
onMounted(() => {
  if (!config.config) config.fetch().catch(() => {})
  measure()
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    ro = new ResizeObserver(measure)
    ro.observe(root.value)
    if (root.value.firstElementChild) ro.observe(root.value.firstElementChild)
  }
})
onBeforeUnmount(() => ro?.disconnect())
watch(
  () => shoot.mode,
  () => nextTick(measure),
)
const triggerOnly = computed(() => !shoot.downloads && shoot.mode === 'single')
const whereName = computed(() => storage.target?.name || storage.target?.label || 'your storage')
const STORAGE_LINK = '#/settings?section=storage'
const savingCardOnly = ref(false)
/** One tap: stop downloading photos, so Single can shoot to the card with no storage chosen. */
async function shootToCardOnly() {
  savingCardOnly.value = true
  try {
    await config.patch({ camera: { download_photos: false } })
  } catch (e) {
    toasts.error(e, { prefix: 'Could not switch to card only' })
  } finally {
    savingCardOnly.value = false
  }
}
const { hints } = useKeyboardHints()

const modes = CAPTURE_MODES.map(({ value, label }) => ({ value, label }))
const modesLocked = computed(() => shoot.anyRunning || capture.inFlight)
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
  <div ref="root" class="side" :class="{ fade: moreBelow }" @scroll.passive="measure">
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
      <p v-if="modesLocked" class="modes-note" data-testid="modes-locked">
        Stop the current capture to change mode.
      </p>
      <div class="shutterwrap">
        <UiButton
          variant="shutter"
          :stop="shoot.stoppable"
          :disabled="!shoot.canPress"
          :aria-label="shoot.label"
          aria-describedby="shutter-reason"
          data-testid="capture-btn"
          @click="shoot.press()"
        />
        <span class="slabel tabular-nums" data-testid="shutter-label">{{ shoot.label }}</span>
        <span class="chip" data-testid="download-chip">
          <template v-if="shoot.noTargetBlocks">Not saving to storage</template>
          <template v-else-if="triggerOnly"><i class="dot" />Trigger only · stays on card</template>
          <template v-else>Downloads to {{ whereName }}</template>
        </span>
        <span id="shutter-reason" class="reason" aria-live="polite" data-testid="shutter-reason">
          <span v-if="shoot.noTargetBlocks" class="notarget" role="status" data-test="no-target">
            <span class="text-camera-warn"
              >No storage chosen. Choose one in Settings › Storage.</span
            >
            <a
              :href="STORAGE_LINK"
              class="inline-flex min-h-[var(--ctl-sm)] items-center underline [html[data-layout='touch']_&]:min-h-11"
              @click.prevent="emit('open-settings', 'storage')"
            >
              Open storage settings
            </a>
            <UiButton
              v-if="shoot.mode === 'single'"
              size="sm"
              :loading="savingCardOnly"
              @click="shootToCardOnly"
            >
              Shoot to card only
            </UiButton>
          </span>
          <template v-else-if="shoot.blockedReason && !shoot.stoppable">{{
            shoot.blockedReason
          }}</template>
          <span v-else-if="hints" class="kbdonly"><kbd>Space</kbd></span>
        </span>
      </div>
      <div v-if="settingsView" class="msettings">
        <component :is="settingsView" @navigate="(...a) => emit('navigate', ...a)" />
      </div>
    </div>

    <div
      v-if="first || (capture.lastError && !shoot.noTarget)"
      class="lastinfo"
      data-testid="last-capture"
    >
      <template v-if="first">
        <span class="eyebrow">Last capture</span>
        <span class="nm" :title="first.name">{{ first.name }}</span>
        <span class="text-camera-muted">
          {{ kinds || 'On the camera card' }}
          <template v-if="result.files?.length > 1"> · {{ result.files.length }} files</template>
        </span>
      </template>
      <span
        v-else-if="capture.lastError && !shoot.noTarget"
        class="text-camera-danger"
        role="alert"
      >
        {{ capture.lastError.message }}
      </span>
    </div>

    <div class="tools">
      <UiButton variant="ghost" size="sm" class="-ml-2.5" @click="cameraSettingsOpen = true">
        <UiIcon name="SlidersHorizontal" :size="16" /> All camera settings
      </UiButton>
      <UiButton variant="ghost" size="sm" class="-mr-2.5" @click="recordingOpen = true">
        <UiIcon name="Video" :size="16" /> Record video
      </UiButton>
    </div>

    <UiModal
      :open="cameraSettingsOpen"
      title="All camera settings"
      class="[html[data-layout='touch']_&]:!max-w-3xl"
      @close="cameraSettingsOpen = false"
    >
      <SettingsPanel />
    </UiModal>
    <UiModal :open="recordingOpen" title="Record video" @close="recordingOpen = false">
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
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: theme('colors.camera.muted');
  border: 1px solid theme('colors.camera.subtle');
  border-radius: 999px;
  padding: 2px 10px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: theme('colors.camera.warn');
}
.modes-note {
  margin: -8px 0 0;
  font-size: 12px;
  color: theme('colors.camera.muted');
}
.reason {
  min-height: 20px;
  font-size: 12px;
  color: theme('colors.camera.muted');
  text-align: center;
}
.notarget {
  display: grid;
  justify-items: center;
  gap: 6px;
  font-size: 13px;
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
    500 12px ui-monospace,
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
html[data-layout='touch'] .sidecard {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  align-items: center;
  column-gap: 24px;
}
html[data-layout='touch'] .sidecard .modes {
  grid-column: 1 / -1;
}
html[data-layout='touch'] .sidecard:not(.has) .shutterwrap {
  grid-column: 1 / -1;
}
html[data-layout='touch'] .msettings {
  border-top: 0;
  padding-top: 0;
}
@media (max-width: 560px) {
  html[data-layout='touch'] .sidecard {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (min-width: 900px) and (orientation: landscape) {
  html[data-layout='touch'] .sidecard {
    grid-template-columns: minmax(0, 1fr);
  }
  html[data-layout='touch'] .msettings {
    border-top: 1px solid theme('colors.camera.subtle');
    padding-top: 16px;
  }
}
.side.fade {
  -webkit-mask-image: linear-gradient(#000 calc(100% - 40px), transparent);
  mask-image: linear-gradient(#000 calc(100% - 40px), transparent);
}
html[data-layout='touch'] .kbdonly {
  display: none;
}
html[data-layout='touch'] .lastinfo {
  display: none;
}
</style>
