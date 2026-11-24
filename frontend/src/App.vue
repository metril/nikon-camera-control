<script setup>
/**
 * App shell. Views are kept alive (<KeepAlive>) so live view / time-lapse state survives tab switches.
 * How a view learns it is hidden/visible:
 *   - onActivated()/onDeactivated() (Vue lifecycle hooks, fire on first mount too), and/or
 *   - inject('activeTab') - a readonly ref with the current tab id ('shoot' | 'timelapse' | ...).
 */
import { computed, provide, readonly, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import { useHotkeys } from '@/composables'
import { useLayoutMode } from '@/composables/useLayoutMode'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiModal from '@/components/ui/UiModal.vue'
import AppHeader from '@/components/shell/AppHeader.vue'
import ApiKeyPrompt from '@/components/shell/ApiKeyPrompt.vue'
import JobsPanel from '@/components/shell/JobsPanel.vue'
import ToastHost from '@/components/shell/ToastHost.vue'
import { TABS, useTabs } from '@/components/shell/useTabs'
import { useCameraStatus } from '@/components/shell/useCameraStatus'
import ShootView from '@/views/ShootView.vue'
import TimelapseView from '@/views/TimelapseView.vue'
import GalleryView from '@/views/GalleryView.vue'
import SettingsView from '@/views/SettingsView.vue'

const auth = useAuthStore()
const events = useEventsStore()
const { isTouch } = useLayoutMode()
const { stripe } = useCameraStatus()

const VIEWS = {
  shoot: ShootView,
  timelapse: TimelapseView,
  gallery: GalleryView,
  settings: SettingsView,
}
const { activeTab, select } = useTabs()
const current = computed(() => VIEWS[activeTab.value])
provide('activeTab', readonly(activeTab))
// Cross-tab navigation for views: inject('navigate')('gallery'). Also handled: open-gallery/open-timelapse/open-settings events.
provide('navigate', select)

// The no-key bar's height is published as --banner so full-height views can subtract it.
let bannerObserver = null
function measureBanner(el) {
  bannerObserver?.disconnect()
  bannerObserver = null
  const set = () =>
    document.documentElement.style.setProperty('--banner', `${el ? el.offsetHeight : 0}px`)
  set()
  if (el && typeof ResizeObserver !== 'undefined') {
    bannerObserver = new ResizeObserver(set)
    bannerObserver.observe(el)
  }
}

const helpOpen = ref(false)
const jobsOpen = ref(false)
const anyModalOpen = () => !!document.querySelector('[aria-modal="true"]')

function shortcut(fn) {
  return () => {
    if (!anyModalOpen()) fn()
  }
}
// useHotkeys ignores keys typed in inputs/buttons. Space and A, S, I, E belong to the Shoot view.
useHotkeys({
  g: shortcut(() => select('gallery')),
  t: shortcut(() => select('timelapse')),
  '?': shortcut(() => (helpOpen.value = true)),
})

const SHORTCUTS = [
  [['Space'], 'Take a photo (Shoot)'],
  [['A', 'S', 'I', 'E'], 'Aperture, shutter speed, ISO, exposure compensation (Shoot)'],
  [['[', ']'], 'Previous and next value (Shoot)'],
  [['G'], 'Open Gallery'],
  [['T'], 'Open Time-lapse'],
  [['?'], 'Show this help'],
  [['Esc'], 'Close dialogs'],
]
</script>

<template>
  <div class="flex min-h-screen flex-col bg-camera-bg">
    <AppHeader
      :active-tab="activeTab"
      @select="select"
      @jobs="jobsOpen = true"
      @shortcuts="helpOpen = true"
    />
    <div class="stripe" :class="stripe" data-test="stripe" aria-hidden="true" />

    <a
      v-if="auth.authEnabled === false"
      :ref="measureBanner"
      href="#/settings"
      class="warn-bar"
      data-test="no-key-warning"
    >
      <UiIcon name="TriangleAlert" :size="16" />
      No API key set. Anyone on the network can control the camera. Set one in Settings.
    </a>
    <UiAlert
      v-if="events.status === 'forbidden'"
      tone="danger"
      class="mx-4 mt-4"
      title="This page's address is not allowed"
      data-test="origin-blocked"
    >
      The server rejected this page's address. Add it to Allowed origins in Settings, then reload.
      <template #action>
        <UiButton size="sm" @click="select('settings')">Open Settings</UiButton>
      </template>
    </UiAlert>

    <main class="main">
      <KeepAlive>
        <component
          :is="current"
          @open-gallery="select('gallery')"
          @open-timelapse="select('timelapse')"
          @open-settings="select('settings')"
        />
      </KeepAlive>
    </main>

    <nav v-if="isTouch" class="bottomnav" aria-label="Sections" data-test="bottomnav">
      <a
        v-for="t in TABS"
        :key="t.id"
        :href="`#/${t.id}`"
        :aria-current="activeTab === t.id ? 'page' : undefined"
        @click.prevent="select(t.id)"
      >
        <UiIcon :name="t.icon" :size="22" />
        <span>{{ t.label }}</span>
      </a>
    </nav>

    <JobsPanel :open="jobsOpen" @close="jobsOpen = false" />
    <ApiKeyPrompt />
    <ToastHost />

    <UiModal :open="helpOpen" title="Keyboard shortcuts" @close="helpOpen = false">
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 text-sm">
        <template v-for="[keys, d] in SHORTCUTS" :key="d">
          <dt class="flex gap-1">
            <kbd v-for="k in keys" :key="k">{{ k }}</kbd>
          </dt>
          <dd>{{ d }}</dd>
        </template>
      </dl>
    </UiModal>
  </div>
</template>

<style>
:root {
  --nav: 0px;
}
html[data-layout='touch'] {
  --nav: 69px;
}
</style>

<style scoped>
.stripe {
  height: 3px;
  background: transparent;
  transition: background-color 200ms;
}
.stripe.off {
  background: theme('colors.camera.danger');
}
.stripe.busy {
  background: theme('colors.camera.warn');
}
.warn-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 16px;
  background: theme('colors.camera.raised');
  border-bottom: 1px solid theme('colors.camera.subtle');
  color: theme('colors.camera.warn');
  font-size: 13px;
  text-align: center;
}
.main {
  flex: 1;
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 16px max(16px, env(safe-area-inset-right, 0px)) calc(24px + var(--nav))
    max(16px, env(safe-area-inset-left, 0px));
}
kbd {
  display: inline-block;
  padding: 1px 6px;
  border: 1px solid theme('colors.camera.border');
  border-bottom-width: 2px;
  border-radius: 4px;
  background: theme('colors.camera.raised');
  font:
    500 11px/16px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
}
.bottomnav {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 20;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  background: theme('colors.camera.surface');
  border-top: 1px solid theme('colors.camera.subtle');
  padding: 6px max(8px, env(safe-area-inset-left, 0px)) calc(6px + env(safe-area-inset-bottom, 0px))
    max(8px, env(safe-area-inset-right, 0px));
}
.bottomnav a {
  display: grid;
  justify-items: center;
  gap: 3px;
  min-height: 56px;
  padding: 6px 0;
  border-radius: theme('borderRadius.inner');
  color: theme('colors.camera.muted');
  font-size: 11px;
  font-weight: 500;
  text-decoration: none;
}
.bottomnav a:active {
  background: theme('colors.camera.raised');
}
.bottomnav a[aria-current='page'] {
  color: theme('colors.camera.accent');
}
</style>
