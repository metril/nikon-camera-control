<script setup>
/** Top bar: brand, tabs, camera status chip, battery, shots left, Jobs and (desktop only) the layout switch. */
import { computed, onMounted, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useJobsStore } from '@/stores/jobs'
import { useStorageStore } from '@/stores/storage'
import { useVisiblePolling } from '@/composables'
import { useLayoutMode } from '@/composables/useLayoutMode'
import UiIcon from '@/components/ui/UiIcon.vue'
import CameraChip from './CameraChip.vue'
import { TABS } from './useTabs'
import { shotsLeftOf } from './shotsLeft'

defineProps({ activeTab: { type: String, required: true } })
const emit = defineEmits(['select', 'jobs', 'shortcuts'])

const camera = useCameraStore()
const capture = useCaptureStore()
const jobs = useJobsStore()
const storage = useStorageStore()
const { layout, forced, setPref } = useLayoutMode()

const battery = computed(() => {
  const b = camera.battery
  if (!b) return null
  if (typeof b.percent === 'number') return `${Math.round(b.percent)}%`
  return b.level != null ? String(b.level) : null
})
const shotsLeft = computed(() => {
  const cards = camera.storage?.cards
  if (!cards?.length) return null
  const n = shotsLeftOf(cards)
  return n == null ? '–' : n.toLocaleString('en-GB') // a camera that does not report it: unknown, not 0
})

const refresh = () => {
  // the card is unavailable (409) while another feature holds the camera
  if (camera.connected && !camera.leasedBy) camera.fetchStorage().catch(() => {})
}
watch(() => [camera.connected, camera.leasedBy], refresh)
watch(
  () => capture.inFlight,
  (busy, was) => was && !busy && refresh(), // a shot just landed: shots left changed
)
onMounted(() => {
  refresh()
  if (!storage.loaded) storage.refresh().catch(() => {})
})
useVisiblePolling(refresh, 60000)

const LAYOUTS = [
  { value: 'desktop', label: 'Desktop', icon: 'Monitor' },
  { value: 'touch', label: 'Touch', icon: 'Hand' },
]
</script>

<template>
  <header class="top" data-test="header">
    <div class="brand">
      <span class="logo"><UiIcon name="Camera" :size="18" /></span>
      <span class="name">Nikon Camera Control</span>
    </div>
    <nav class="tabs" aria-label="Primary">
      <a
        v-for="t in TABS"
        :key="t.id"
        :href="`#/${t.id}`"
        :aria-current="activeTab === t.id ? 'page' : undefined"
        @click.prevent="emit('select', t.id)"
      >
        {{ t.label }}
      </a>
    </nav>
    <div class="status">
      <CameraChip />
      <span v-if="battery" class="stat batt" title="Battery" data-test="battery">
        <UiIcon name="Battery" :size="16" label="Battery" /><span class="tabular-nums">{{
          battery
        }}</span>
      </span>
      <span v-if="shotsLeft" class="stat shots" title="Shots left on the card" data-test="shots">
        <UiIcon name="HardDrive" :size="16" label="Shots left" /><span class="tabular-nums">{{
          shotsLeft
        }}</span>
      </span>
      <button
        type="button"
        class="iconbtn keys"
        aria-label="Keyboard shortcuts"
        title="Keyboard shortcuts (?)"
        data-test="shortcuts-button"
        @click="emit('shortcuts')"
      >
        <UiIcon name="Keyboard" />
      </button>
      <button
        type="button"
        class="iconbtn"
        :aria-label="jobs.active.length ? `Jobs, ${jobs.active.length} running` : 'Jobs'"
        title="Jobs"
        data-test="jobs-button"
        @click="emit('jobs')"
      >
        <UiIcon name="ListChecks" />
        <span v-if="jobs.active.length" class="count tabular-nums" data-test="jobs-count">{{
          jobs.active.length
        }}</span>
      </button>
      <div v-if="!forced && layout !== 'touch'" class="seg" role="group" aria-label="Layout">
        <button
          v-for="l in LAYOUTS"
          :key="l.value"
          type="button"
          :aria-pressed="layout === l.value"
          :aria-label="`${l.label} layout`"
          :title="`${l.label} layout`"
          :data-test="`layout-${l.value}`"
          @click="setPref(l.value)"
        >
          <UiIcon :name="l.icon" :size="16" /><span class="lbl">{{ l.label }}</span>
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.top {
  position: sticky;
  top: env(safe-area-inset-top, 0px);
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 16px;
  height: 56px;
  background: theme('colors.camera.surface');
  border-bottom: 1px solid theme('colors.camera.subtle');
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
}
.logo {
  width: 28px;
  height: 28px;
  border-radius: theme('borderRadius.inner');
  background: theme('colors.camera.accent');
  color: theme('colors.camera.accent-ink');
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.tabs {
  display: flex;
  gap: 4px;
  height: 100%;
  margin-left: 8px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.tabs a {
  position: relative;
  display: inline-flex;
  align-items: center;
  height: 100%;
  padding: 0 12px;
  color: theme('colors.camera.muted');
  font-weight: 500;
  white-space: nowrap;
  text-decoration: none;
}
.tabs a:hover {
  color: theme('colors.camera.text');
}
.tabs a:active {
  background: theme('colors.camera.raised');
}
.tabs a[aria-current='page'] {
  color: theme('colors.camera.text');
}
.tabs a[aria-current='page']::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: -1px;
  height: 2px;
  border-radius: 2px;
  background: theme('colors.camera.accent');
}
.status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.stat {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: theme('colors.camera.muted');
  font-size: 13px;
  white-space: nowrap;
}
.iconbtn {
  position: relative;
  width: var(--ctl-sm);
  height: var(--ctl-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: theme('borderRadius.control');
  border: 1px solid transparent;
  background: none;
  color: theme('colors.camera.muted');
  cursor: pointer;
}
.iconbtn:hover {
  background: theme('colors.camera.raised');
  color: theme('colors.camera.text');
}
.iconbtn:active {
  background: theme('colors.camera.hover');
  color: theme('colors.camera.text');
}
.count {
  position: absolute;
  top: -2px;
  right: -2px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 9999px;
  background: theme('colors.camera.accent');
  color: theme('colors.camera.accent-ink');
  font:
    600 12px/16px system-ui,
    sans-serif;
  text-align: center;
}
.seg {
  display: inline-flex;
  gap: 2px;
  height: var(--ctl-sm);
  padding: 2px;
  background: theme('colors.camera.bg');
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.control');
}
.seg button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 10px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: theme('colors.camera.muted');
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.seg button:hover {
  color: theme('colors.camera.text');
}
.seg button:active:not([aria-pressed='true']) {
  background: theme('colors.camera.subtle');
}
.seg button[aria-pressed='true'] {
  background: theme('colors.camera.raised');
  color: theme('colors.camera.text');
  box-shadow: inset 0 0 0 1px theme('colors.camera.border');
}

/* The header must not overflow between 820 and 1180px */
@media (max-width: 1180px) {
  .shots,
  .lbl,
  .name {
    display: none;
  }
}
@media (max-width: 820px) {
  .tabs a {
    padding: 0 8px;
  }
  .tabs a[aria-current='page']::after {
    left: 8px;
    right: 8px;
  }
  .batt {
    display: none;
  }
}
/* Touch: the tabs move to the bottom bar */
html[data-layout='touch'] .top {
  height: 60px;
}
html[data-layout='touch'] .keys,
html[data-layout='touch'] .tabs,
html[data-layout='touch'] .shots,
html[data-layout='touch'] .lbl {
  display: none;
}
html[data-layout='touch'] .name {
  display: inline;
}
@media (max-width: 560px) {
  html[data-layout='touch'] .name {
    display: none;
  }
}
</style>
