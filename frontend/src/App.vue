<script setup>
import { useCameraStore } from './stores/camera'
import { useCaptureStore } from './stores/capture'
import { useToastsStore } from './stores/toasts'
import { useHotkeys } from './composables/useHotkeys'
import LiveView from './components/LiveView.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import CaptureControls from './components/CaptureControls.vue'
import StatusBar from './components/StatusBar.vue'
import ModeWarning from './components/ModeWarning.vue'
import Gallery from './components/Gallery.vue'
import Timelapse from './components/Timelapse.vue'

// STUB (foundation pass): events/status are driven by stores/events.js (started in main.js);
// the old inline WebSocket was removed. Components are rewritten separately.
const camera = useCameraStore()
const capture = useCaptureStore()
const toasts = useToastsStore()

useHotkeys({
  ' ': () => {
    if (camera.isReady) capture.capture().catch((e) => toasts.error(e))
  },
})
</script>

<template>
  <div class="min-h-screen bg-camera-bg flex flex-col">
    <!-- Header -->
    <header class="bg-camera-surface border-b border-camera-border px-4 py-3">
      <div class="flex items-center gap-3">
        <svg class="w-8 h-8 text-camera-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <h1 class="text-xl font-semibold">Nikon D500 Control</h1>
      </div>
    </header>

    <!-- Status Bar -->
    <div class="px-4 py-2 bg-camera-bg">
      <StatusBar />
    </div>

    <!-- Mode dial warning -->
    <div class="px-4">
      <ModeWarning />
    </div>

    <!-- Main content -->
    <main class="flex-1 flex flex-col lg:flex-row gap-4 p-4">
      <!-- Live View (left/top) -->
      <div class="lg:flex-1 flex flex-col gap-4">
        <LiveView />
        <div class="flex flex-col sm:flex-row gap-4">
          <div class="sm:w-48">
            <CaptureControls />
          </div>
          <div class="flex-1">
            <Gallery />
          </div>
        </div>
      </div>

      <!-- Settings Panel (right/bottom) -->
      <aside class="lg:w-80 xl:w-96 space-y-4">
        <SettingsPanel />
        <Timelapse />
      </aside>
    </main>

    <!-- Error toast -->
    <div
      v-if="camera.lastError"
      class="fixed bottom-4 right-4 bg-camera-error text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 max-w-md"
    >
      <span class="flex-1">{{ camera.lastError.message }}</span>
      <button
        @click="camera.lastError = null"
        class="text-white/80 hover:text-white"
      >
        &times;
      </button>
    </div>

    <!-- Keyboard shortcuts hint -->
    <footer class="bg-camera-surface border-t border-camera-border px-4 py-2 text-xs text-camera-muted">
      <span class="mr-4"><kbd class="px-1.5 py-0.5 bg-camera-border rounded">Space</kbd> Capture</span>
      <span class="mr-4"><kbd class="px-1.5 py-0.5 bg-camera-border rounded">H</kbd> Histogram</span>
      <span><kbd class="px-1.5 py-0.5 bg-camera-border rounded">G</kbd> Grid</span>
    </footer>
  </div>
</template>
