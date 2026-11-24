<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useCameraStore } from '@/stores/camera'
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

const camera = useCameraStore()
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
const listen = () => document.addEventListener('keydown', onKeydown)
const unlisten = () => document.removeEventListener('keydown', onKeydown)
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
      <CaptureSide class="side-area" @navigate="go" @open-settings="go('settings')" />
      <RecentCaptures class="film-area" @open-gallery="go('gallery')" />
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

/* Touch, landscape (kiosk screens): live view and controls side by side with no scrolling */
@media (min-width: 900px) and (orientation: landscape) {
  html[data-layout='touch'] .shoot {
    --lvw: min(100%, calc((100dvh - 60px - var(--nav) - 64px - 64px) * 1.5));
    grid-template-columns: minmax(0, 1fr) 340px;
    grid-template-areas:
      'strip side'
      'lv side'
      'film film';
    align-items: start;
  }
  html[data-layout='touch'] .strip-area {
    display: flex;
    gap: 0;
    width: var(--lvw);
    background: theme('colors.camera.surface');
    border: 1px solid theme('colors.camera.subtle');
    border-radius: theme('borderRadius.card');
    overflow: hidden;
  }
  html[data-layout='touch'] .strip-area :deep(.cell) {
    border: 0;
    border-radius: 0;
    background: none;
    min-height: 64px;
  }
  html[data-layout='touch'] .strip-area :deep(.cell + .cell) {
    border-left: 1px solid theme('colors.camera.subtle');
  }
  html[data-layout='touch'] .strip-area :deep(.cell .v) {
    font-size: 19px;
  }
  html[data-layout='touch'] .strip-area :deep(.cell .auto) {
    display: none;
  }
  html[data-layout='touch'] .lvwrap {
    width: var(--lvw);
  }
  html[data-layout='touch'] .side-area {
    position: sticky;
    top: 76px;
    max-height: calc(100dvh - 60px - var(--nav) - 32px);
    overflow-y: auto;
  }
}
</style>
