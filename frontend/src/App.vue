<script setup>
/**
 * App shell. Views are kept alive (<KeepAlive>) so live view / time-lapse state survives tab switches.
 * How a view learns it is hidden/visible:
 *   - onActivated()/onDeactivated() (Vue lifecycle hooks, fire on first mount too), and/or
 *   - inject('activeTab') - a readonly ref with the current tab id ('shoot' | 'timelapse' | ...).
 */
import { computed, provide, readonly, ref } from 'vue'
import { useEventsStore } from '@/stores/events'
import { useHotkeys } from '@/composables'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiModal from '@/components/ui/UiModal.vue'
import AppHeader from '@/components/shell/AppHeader.vue'
import LoginScreen from '@/components/shell/LoginScreen.vue'
import AuthBanner from '@/components/shell/AuthBanner.vue'
import JobsPanel from '@/components/shell/JobsPanel.vue'
import ToastHost from '@/components/shell/ToastHost.vue'
import OnScreenKeyboard from '@/components/shell/OnScreenKeyboard.vue'
import KioskSleepOverlay from '@/components/shell/KioskSleepOverlay.vue'
import { TABS, useTabs } from '@/components/shell/useTabs'
import { useCameraStatus } from '@/components/shell/useCameraStatus'
import LiveViewPopout from '@/views/LiveViewPopout.vue'
import ShootView from '@/views/ShootView.vue'
import TimelapseView from '@/views/TimelapseView.vue'
import GalleryView from '@/views/GalleryView.vue'
import SettingsView from '@/views/SettingsView.vue'

// ?popout=liveview: this window shows only the live view (opened from Shoot)
const popout = (() => {
  try {
    return new URLSearchParams(location.search).get('popout') === 'liveview'
  } catch {
    return false
  }
})()

const events = useEventsStore()
const { stripe } = useCameraStatus()

const VIEWS = {
  shoot: ShootView,
  timelapse: TimelapseView,
  gallery: GalleryView,
  settings: SettingsView,
}
const { activeTab, select } = useTabs()
const current = computed(() => VIEWS[activeTab.value])
const tabLabel = computed(() => TABS.find((t) => t.id === activeTab.value)?.label || '')
const mainEl = ref(null)
const focusMain = () => mainEl.value?.focus()
// Views emit open-settings with an optional section id ('storage', 'security', ...).
const openQuery = (section) => (typeof section === 'string' ? { section } : undefined)
provide('activeTab', readonly(activeTab))
// Cross-tab navigation for views: inject('navigate')('gallery'). Also handled: open-gallery/open-timelapse/open-settings events.
provide('navigate', select)

// The no-password bar's height is published as --banner so full-height views can subtract it.
let bannerObserver = null
function measureBanner(comp) {
  const el = comp?.$el?.nodeType === 1 ? comp.$el : null // a comment node while no banner shows
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
  <div v-if="popout" data-test="popout-frame">
    <LiveViewPopout />
    <LoginScreen />
    <ToastHost />
  </div>
  <div v-else class="app-frame flex flex-col bg-camera-bg" data-test="app-frame">
    <a href="#main" class="skip" data-test="skip" @click.prevent="focusMain"
      >Skip to main content</a
    >
    <AppHeader
      :active-tab="activeTab"
      @select="select"
      @jobs="jobsOpen = true"
      @shortcuts="helpOpen = true"
    />
    <div class="stripe" :class="stripe" data-test="stripe" aria-hidden="true" />

    <AuthBanner :ref="measureBanner" @open-security="select('settings', { section: 'security' })" />
    <UiAlert
      v-if="events.status === 'forbidden'"
      tone="danger"
      class="mx-4 mt-4"
      title="This page's address is not allowed"
      data-test="origin-blocked"
    >
      The server rejected this page's address. Add it to Allowed origins in Settings, then reload.
      <template #action>
        <UiButton size="sm" @click="select('settings', { section: 'general' })">
          Open settings
        </UiButton>
      </template>
    </UiAlert>

    <main id="main" ref="mainEl" class="main" tabindex="-1">
      <h1 class="sr-only" data-test="view-title">{{ tabLabel }}</h1>
      <KeepAlive>
        <component
          :is="current"
          @open-gallery="select('gallery')"
          @open-timelapse="select('timelapse')"
          @open-settings="(section) => select('settings', openQuery(section))"
        />
      </KeepAlive>
    </main>

    <JobsPanel :open="jobsOpen" @close="jobsOpen = false" />
    <LoginScreen />
    <ToastHost />
    <OnScreenKeyboard />
    <KioskSleepOverlay />

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
.skip {
  position: absolute;
  left: 8px;
  top: -100px;
  z-index: 60;
  padding: 10px 14px;
  border-radius: theme('borderRadius.control');
  background: theme('colors.camera.accent');
  color: theme('colors.camera.accent-ink');
  font-weight: 600;
}
.skip:focus {
  top: 8px;
}
.main:focus {
  outline: none;
}
.stripe {
  flex: none;
}
.main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 16px max(16px, env(safe-area-inset-right, 0px)) 24px
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
html[data-layout='touch'] kbd {
  font-size: var(--fs-min);
}
</style>
