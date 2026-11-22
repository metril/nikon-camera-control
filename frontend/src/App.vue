<script setup>
/**
 * App shell. Views are kept alive (<KeepAlive>) so live view / time-lapse state survives tab switches.
 * How a view learns it is hidden/visible:
 *   - onActivated()/onDeactivated() (Vue lifecycle hooks, fire on first mount too), and/or
 *   - inject('activeTab') - a readonly ref with the current tab id ('shoot' | 'timelapse' | ...).
 */
import { computed, provide, readonly, ref } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useToastsStore } from '@/stores/toasts'
import { useAuthStore } from '@/stores/auth'
import { useJobsStore } from '@/stores/jobs'
import { useHotkeys } from '@/composables'
import UiModal from '@/components/ui/UiModal.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import StatusBar from '@/components/shell/StatusBar.vue'
import ToastHost from '@/components/shell/ToastHost.vue'
import ApiKeyPrompt from '@/components/shell/ApiKeyPrompt.vue'
import JobsPanel from '@/components/shell/JobsPanel.vue'
import { TABS, useTabs } from '@/components/shell/useTabs'
import ShootView from '@/views/ShootView.vue'
import TimelapseView from '@/views/TimelapseView.vue'
import GalleryView from '@/views/GalleryView.vue'
import AdvancedView from '@/views/AdvancedView.vue'
import SettingsView from '@/views/SettingsView.vue'

const camera = useCameraStore()
const capture = useCaptureStore()
const toasts = useToastsStore()
const auth = useAuthStore()
const jobs = useJobsStore()

const VIEWS = {
  shoot: ShootView,
  timelapse: TimelapseView,
  gallery: GalleryView,
  advanced: AdvancedView,
  settings: SettingsView,
}
const { activeTab, select } = useTabs()
const current = computed(() => VIEWS[activeTab.value])
provide('activeTab', readonly(activeTab))
// Cross-tab navigation for views: inject('navigate')('gallery'). Also handled: open-gallery/open-timelapse/open-settings events.
provide('navigate', select)

const helpOpen = ref(false)
const jobsOpen = ref(false)
const anyModalOpen = () => !!document.querySelector('[aria-modal="true"]')

function shortcut(fn) {
  return () => {
    if (!anyModalOpen()) fn()
  }
}
// useHotkeys ignores keys typed in inputs/buttons, so Space on a focused button only clicks it.
useHotkeys({
  ' ': shortcut(() => {
    if (activeTab.value !== 'shoot') return
    if (camera.leasedBy) return toasts.info(`Busy: ${camera.leasedBy}`)
    // same gate as the Capture button: live view does not block shooting
    if (camera.connected && ['idle', 'liveview'].includes(camera.state) && !capture.inFlight)
      capture.capture().catch((e) => toasts.error(e))
  }),
  g: shortcut(() => select('gallery')),
  t: shortcut(() => select('timelapse')),
  '?': shortcut(() => (helpOpen.value = true)),
})

const SHORTCUTS = [
  ['Space', 'Capture (Shoot tab)'],
  ['g', 'Open Gallery'],
  ['t', 'Open Time-lapse'],
  ['?', 'Show this help'],
  ['Esc', 'Close dialogs'],
]
</script>

<template>
  <div class="flex min-h-screen flex-col bg-camera-bg">
    <header class="border-b border-camera-border bg-camera-surface px-4 py-3">
      <div class="flex flex-wrap items-center gap-3">
        <svg
          class="h-7 w-7 shrink-0 text-camera-accent"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.5"
            d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"
          />
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="1.5"
            d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
          />
        </svg>
        <h1 class="text-lg font-semibold">Nikon Camera Control</h1>
        <a
          v-if="auth.authEnabled === false"
          href="#/settings"
          class="rounded-full focus-visible:outline-offset-2"
          data-test="no-key-warning"
          title="No API key set — anyone on the network can control the camera"
        >
          <UiBadge tone="warn"
            >No API key set — anyone on the network can control the camera</UiBadge
          >
        </a>
        <button
          type="button"
          class="ml-auto inline-flex items-center gap-2 rounded-md border border-camera-border px-3 py-1.5 text-sm hover:bg-camera-border"
          data-test="jobs-button"
          @click="jobsOpen = true"
        >
          Jobs
          <UiBadge v-if="jobs.active.length" tone="info" data-test="jobs-count">
            {{ jobs.active.length }}
          </UiBadge>
        </button>
        <button
          type="button"
          class="rounded-md border border-camera-border px-2.5 py-1.5 text-sm hover:bg-camera-border"
          aria-label="Keyboard shortcuts"
          @click="helpOpen = true"
        >
          ?
        </button>
      </div>
      <nav aria-label="Primary" class="-mb-3 mt-3 flex gap-1 overflow-x-auto">
        <a
          v-for="t in TABS"
          :key="t.id"
          :href="`#/${t.id}`"
          :aria-current="activeTab === t.id ? 'page' : undefined"
          class="whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors"
          :class="
            activeTab === t.id
              ? 'border-camera-accent text-camera-text'
              : 'border-transparent text-camera-muted hover:text-camera-text'
          "
          @click.prevent="select(t.id)"
        >
          {{ t.label }}
        </a>
      </nav>
    </header>

    <div class="border-b border-camera-border bg-camera-bg px-4 py-2">
      <StatusBar />
    </div>

    <main class="flex-1 p-4">
      <KeepAlive>
        <component
          :is="current"
          @open-gallery="select('gallery')"
          @open-timelapse="select('timelapse')"
          @open-settings="select('settings')"
        />
      </KeepAlive>
    </main>

    <JobsPanel :open="jobsOpen" @close="jobsOpen = false" />
    <ApiKeyPrompt />
    <ToastHost />

    <UiModal :open="helpOpen" title="Keyboard shortcuts" @close="helpOpen = false">
      <dl class="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
        <template v-for="[k, d] in SHORTCUTS" :key="k">
          <dt>
            <kbd class="rounded bg-camera-border px-1.5 py-0.5">{{ k }}</kbd>
          </dt>
          <dd>{{ d }}</dd>
        </template>
      </dl>
    </UiModal>
  </div>
</template>
