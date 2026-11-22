<script setup>
import { computed, watch, onMounted } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useEventsStore } from '@/stores/events'
import { useToastsStore } from '@/stores/toasts'
import { useAsync, useVisiblePolling } from '@/composables'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { formatBytes } from './format'

const camera = useCameraStore()
const events = useEventsStore()
const toasts = useToastsStore()

const TONES = {
  disconnected: 'neutral',
  connecting: 'info',
  idle: 'ok',
  liveview: 'ok',
  capturing: 'warn',
  recording: 'warn',
  bulb: 'warn',
  busy: 'warn',
  error: 'error',
}
const tone = computed(() => TONES[camera.state] || 'neutral')

const SOCKET = {
  open: { tone: 'ok', text: 'Live' },
  connecting: { tone: 'info', text: 'Connecting' },
  closed: { tone: 'warn', text: 'Offline' },
  unauthorized: { tone: 'error', text: 'Key needed' },
  forbidden: { tone: 'error', text: 'Origin not allowed' },
}
const socket = computed(() => SOCKET[events.status] || SOCKET.closed)

const battery = computed(() => {
  const b = camera.battery
  if (!b) return null
  if (typeof b.percent === 'number') return `${Math.round(b.percent)}%`
  return b.level != null ? String(b.level) : null
})
const free = computed(() => {
  const cards = camera.storage?.cards
  if (!cards?.length) return null
  return formatBytes(cards.reduce((n, c) => n + (c.free_kb || 0), 0) * 1024)
})

const toggle = useAsync(() => (camera.connected ? camera.disconnect() : camera.connect()))
const busy = computed(() => toggle.loading.value || camera.state === 'connecting')
function onToggle() {
  toggle.run().catch((e) => toasts.error(e))
}

const refresh = () => {
  // the card is unavailable (409) while another feature holds the camera
  if (camera.connected && !camera.leasedBy) camera.fetchStorage().catch(() => {})
}
watch(() => [camera.connected, camera.leasedBy], refresh)
onMounted(refresh)
useVisiblePolling(refresh, 60000)
</script>

<template>
  <div class="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" aria-live="polite">
    <UiBadge :tone="tone" data-test="state">{{ camera.stateDescription }}</UiBadge>
    <span v-if="camera.model" class="text-camera-text" data-test="model">{{ camera.model }}</span>
    <span v-if="battery" class="text-camera-muted" data-test="battery">Battery {{ battery }}</span>
    <span v-if="free" class="text-camera-muted" data-test="storage">{{ free }} free</span>
    <UiBadge v-if="camera.leasedBy" tone="warn" data-test="lease"
      >Busy: {{ camera.leasedBy }}</UiBadge
    >
    <span class="flex items-center gap-1 text-camera-muted" data-test="socket">
      Events <UiBadge :tone="socket.tone">{{ socket.text }}</UiBadge>
    </span>
    <span
      v-if="events.status === 'forbidden'"
      class="basis-full text-camera-error"
      role="alert"
      data-test="origin-blocked"
    >
      The server rejected this page's origin. Add it to the allowed origins (cors_origins) in the
      server config, then reload.
    </span>
    <UiButton
      class="ml-auto"
      size="sm"
      :variant="camera.connected ? 'ghost' : 'primary'"
      :loading="busy"
      data-test="toggle"
      @click="onToggle"
    >
      {{ camera.connected ? 'Disconnect' : 'Connect' }}
    </UiButton>
  </div>
</template>
