<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
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

// Keyboard: Space is the shutter; A, S, I and E jump to aperture, shutter, ISO and exposure
// compensation (then [ and ] step the value). Only while this view is the visible one.
const JUMP = { a: 'aperture', s: 'shutter', i: 'iso', e: 'comp' }
function onKeydown(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || e.repeat) return
  if (document.querySelector('[aria-modal="true"]')) return
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
  }
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
  <div class="flex flex-col gap-4">
    <ModeWarning />
    <div class="shoot">
      <ExposureStrip ref="strip" class="strip-area" @navigate="go" />
      <div class="lvwrap">
        <LiveViewPanel v-if="camera.connected" />
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
.shoot {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  grid-template-areas:
    'strip strip'
    'lv side'
    'film film';
  gap: 16px;
}
.strip-area {
  grid-area: strip;
}
.lvwrap {
  grid-area: lv;
  min-width: 0;
}
.side-area {
  grid-area: side;
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

/* Desktop, 1200px and wider: recent captures fill the side column under the shutter */
@media (min-width: 1200px) {
  html[data-layout='desktop'] .shoot {
    grid-template-areas:
      'strip strip'
      'lv side'
      'lv film';
    grid-template-rows: auto auto minmax(0, 1fr);
  }
  html[data-layout='desktop'] .film-area {
    align-self: stretch;
    align-content: start;
    min-height: 0;
  }
}
/* Desktop: the live view never grows taller than what is left under the header, banner and strip,
   so the Shoot page needs no scrolling. 99px = header 56 + stripe 3 + top 16 + bottom 24. */
@media (min-width: 900px) {
  html[data-layout='desktop'] .lvwrap {
    max-width: max(360px, calc((100dvh - 99px - var(--banner, 0px) - 65px - 16px - 2px) * 1.5));
  }
}
/* Desktop, narrow: one column, the strip wraps to two rows */
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
html[data-layout='touch'] .shoot {
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'lv'
    'side'
    'strip'
    'film';
  gap: 12px;
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
html[data-layout='touch'] .strip-area :deep(.cell .v) {
  font-size: 22px;
}
@media (max-width: 560px) {
  html[data-layout='touch'] .strip-area {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* Touch, landscape (kiosk screens): exposure strip over the live view, controls in the side column,
   no scrolling. --lvh is the height left for the live view (LiveViewPanel sizes the frame from it). */
@media (min-width: 900px) and (orientation: landscape) {
  html[data-layout='touch'] .shoot {
    --stripH: 60px;
    --lvh: calc(
      100dvh - 60px - 3px - var(--banner, 0px) - var(--nav) - 16px - 24px - var(--stripH) - 16px -
        4px
    );
    grid-template-columns: minmax(0, 1fr) 340px;
    grid-template-areas:
      'strip side'
      'lv side';
    align-items: start;
  }
  /* no room for the recent captures here: they live in the Gallery */
  html[data-layout='touch'] .film-area {
    display: none;
  }
  /* one row of cells (no filler cells); wraps to more rows only when the values would not fit */
  html[data-layout='touch'] .strip-area {
    display: flex;
    flex-wrap: wrap;
    min-height: var(--stripH);
    background: theme('colors.camera.surface');
    border: 1px solid theme('colors.camera.subtle');
    border-radius: theme('borderRadius.card');
    overflow: hidden;
  }
  html[data-layout='touch'] .strip-area :deep(.cell) {
    flex: 1 1 84px;
    border: 0;
    border-radius: 0;
    background: none;
    box-shadow: 1px 0 0 0 theme('colors.camera.subtle');
    min-height: 0;
    padding: 4px 7px;
    align-content: center;
  }
  html[data-layout='touch'] .strip-area :deep(.cell .v) {
    font-size: 18px;
    overflow: visible;
    text-overflow: clip;
  }
  html[data-layout='touch'] .strip-area :deep(.cell .k) {
    font-size: 11px;
    letter-spacing: 0.04em;
  }
  html[data-layout='touch'] .strip-area :deep(.cell .auto) {
    display: none;
  }
  html[data-layout='touch'] .side-area {
    position: sticky;
    top: 76px;
    max-height: calc(100dvh - 60px - 3px - var(--banner, 0px) - var(--nav) - 40px);
    overflow-y: auto;
    /* overflow-y makes this a scroll container on both axes; room for the ghost buttons' -10px bleed */
    padding-inline: 10px;
    margin-inline: -10px;
  }
}
/* Strip too narrow for one row of 7 cells: two rows */
@media (min-width: 900px) and (max-width: 979px) and (orientation: landscape) {
  html[data-layout='touch'] .shoot {
    --stripH: 108px;
  }
}
</style>
