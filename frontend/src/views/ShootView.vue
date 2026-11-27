<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { oskOpen } from '@/composables/useHotkeys'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useShootStore } from '@/stores/shoot'
import CameraGate from '@/components/shell/CameraGate.vue'
import CaptureSide from '@/components/shoot/CaptureSide.vue'
import ExposureStrip from '@/components/shoot/ExposureStrip.vue'
import LiveViewPanel from '@/components/shoot/LiveViewPanel.vue'
import ModeWarning from '@/components/shoot/ModeWarning.vue'
import RecentCaptures from '@/components/shoot/RecentCaptures.vue'

// Emitted so the shell can switch tabs ('gallery' / 'timelapse' / 'settings').
const emit = defineEmits(['open-gallery', 'open-timelapse', 'open-settings'])
const go = (tab) => emit(`open-${tab}`)
// Deep link: the Gallery opens that file in its lightbox (#/gallery?open=<encoded path>)
function openGallery(file) {
  if (file?.path) location.hash = `#/gallery?open=${encodeURIComponent(file.path)}`
  else go('gallery')
}

const camera = useCameraStore()
const settings = useSettingsStore()
const shoot = useShootStore()
const strip = ref(null)
const lv = ref(null)

// Keyboard: Space is the shutter; A, S, I and E jump to aperture, shutter, ISO and exposure
// compensation (then [ and ] step the value). Only while this view is the visible one.
const JUMP = { a: 'aperture', s: 'shutter', i: 'iso', e: 'comp' }
function onKeydown(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return
  if (document.querySelector('[aria-modal="true"]') || oskOpen()) return
  const t = e.target
  if (t?.closest?.('input, select, textarea, [contenteditable=""], [contenteditable="true"]'))
    return
  if (e.key === ' ') {
    if (t?.closest?.('button, a, [role="button"], summary')) return // let the focused control click
    e.preventDefault()
    shoot.press()
    return
  }
  const cell = JUMP[String(e.key).toLowerCase()]
  if (cell) {
    e.preventDefault()
    strip.value?.focusCell(cell)
    return
  }
  // live view tools and focus keys (3 H C P L O F , . Enter)
  if (camera.connected && lv.value?.hotkey?.(e)) e.preventDefault()
}

// Re-read the exposure strip when this view shows. Fallback for bodies that do not announce
// changes made on the camera: also every 5 s while visible and idle, until the backend has
// seen a property-change event from this body (then events keep the strip in sync).
const SYNC_MS = 5000
let syncTimer = null
function syncExposure() {
  if (document.hidden || !camera.connected || camera.state !== 'idle' || camera.leasedBy) return
  settings.refreshExposure().catch(() => {})
}
function pollExposure() {
  if (!camera.propertyEvents) syncExposure()
}
const listen = () => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('visibilitychange', syncExposure)
  syncExposure()
  if (!syncTimer) syncTimer = setInterval(pollExposure, SYNC_MS)
}
const unlisten = () => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('visibilitychange', syncExposure)
  clearInterval(syncTimer)
  syncTimer = null
}
onMounted(listen)
onActivated(listen)
onDeactivated(unlisten)
onBeforeUnmount(unlisten)
</script>

<template>
  <div class="shootroot">
    <ModeWarning />
    <div class="shoot">
      <ExposureStrip ref="strip" class="strip-area" @navigate="go" />
      <div class="lvwrap">
        <LiveViewPanel v-if="camera.connected" ref="lv" />
        <div v-else class="gate" data-test="lv-gate"><CameraGate /></div>
      </div>
      <CaptureSide
        class="side-area"
        @navigate="go"
        @open-settings="(section) => emit('open-settings', section)"
      />
      <RecentCaptures class="film-area" @open-gallery="openGallery" />
    </div>
  </div>
</template>

<style scoped>
/* The page fills the frame's main area (App.vue fixes the frame to the viewport). Wide landscape
   screens fit everything without scrolling; narrow or portrait ones stack and scroll inside. */
.shootroot {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}
.shootroot > * {
  flex: none;
}
.shoot {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  grid-template-areas:
    'strip strip'
    'lv side'
    'film film';
  grid-template-rows: auto auto auto;
  align-content: start;
  gap: 12px;
  overflow: auto;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}
.strip-area {
  grid-area: strip;
}
.lvwrap {
  grid-area: lv;
  min-width: 0;
  min-height: 0;
}
.side-area {
  grid-area: side;
  min-height: 0;
}
.film-area {
  grid-area: film;
}
.gate {
  display: grid;
  place-items: center;
  aspect-ratio: 3 / 2;
  padding: 16px;
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.subtle');
  border-radius: theme('borderRadius.card');
}

/* Narrow desktop: one column, the strip wraps to two rows */
@media (max-width: 860px) {
  html[data-layout='desktop'] .shoot {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'strip'
      'lv'
      'side'
      'film';
  }
  html[data-layout='desktop'] .strip-area {
    flex-wrap: wrap;
  }
  html[data-layout='desktop'] .strip-area :deep(.cell) {
    flex: 1 1 25%;
    border-bottom: 1px solid theme('colors.camera.subtle');
  }
}

/* Touch, portrait: stacked, exposure values as tiles */
@media (max-width: 899px), (orientation: portrait) {
  html[data-layout='touch'] .shoot {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'lv'
      'side'
      'strip'
      'film';
  }
  html[data-layout='touch'] .strip-area {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    background: none;
    border: 0;
    overflow: visible;
  }
  html[data-layout='touch'] .strip-area :deep(.cell) {
    border: 1px solid theme('colors.camera.subtle');
    border-radius: theme('borderRadius.card');
    background: theme('colors.camera.surface');
    min-height: 76px;
  }
}
@media (max-width: 560px) {
  html[data-layout='touch'] .strip-area {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Wide landscape (desktop and kiosk): strip on top, live view left, the side column right with the
   recent captures under it. Nothing scrolls: the grid is exactly the height of the main area, the
   live view takes the height of its row (--lvh, read by LiveViewPanel) and the side column
   is sized by its content. */
@media (min-width: 900px) and (orientation: landscape) {
  .shoot {
    grid-template-columns: minmax(0, 1fr) 360px;
    grid-template-areas:
      'strip strip'
      'lv side'
      'lv film';
    grid-template-rows: auto auto minmax(0, 1fr);
    align-content: stretch;
    overflow: hidden;
  }
  html[data-layout='touch'] .shoot {
    grid-template-columns: minmax(0, 1fr) 340px;
  }
  .lvwrap {
    container-type: size;
    --lvh: 100cqh;
  }
  .film-area {
    align-self: stretch;
    align-content: start;
    min-height: 0;
    overflow: hidden;
  }
}
</style>
