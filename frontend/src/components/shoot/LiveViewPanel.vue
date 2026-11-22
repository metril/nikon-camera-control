<script setup>
import { ref, computed, watch, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { api, downloadBlob } from '@/api'
import { createLiveViewSocket } from '@/api/ws.js'
import { useCameraStore } from '@/stores/camera'
import { useLiveViewStore } from '@/stores/liveview'
import { useToastsStore } from '@/stores/toasts'
import { useVisibility } from '@/composables'
import UiButton from '@/components/ui/UiButton.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const STALE_MS = 3000
const HIDDEN_CLOSE_MS = 5000

const camera = useCameraStore()
const liveview = useLiveViewStore()
const toasts = useToastsStore()
const visible = useVisibility()

const imgRef = ref(null)
const canvasRef = ref(null)
const stageRef = ref(null)
const canvasMode = ref(false)
const showGrid = ref(false)
const fullscreen = ref(false)
const aspect = ref('3 / 2')
const hasFrame = ref(false)
const stale = ref(false)
const streamStatus = ref(null) // last JSON status message from the socket
const wanted = ref(false) // user pressed Start (or the stream was already running)
const active = ref(true) // view is shown (KeepAlive activated)
const hiddenLong = ref(false)
const starting = ref(false)
const snapshotting = ref(false)

let currentUrl = null
let frameSeq = 0
let staleTimer = null
let hiddenTimer = null
let unmounted = false

function onFrame(buf) {
  clearTimeout(staleTimer)
  staleTimer = setTimeout(() => (stale.value = true), STALE_MS)
  stale.value = false
  const blob = new Blob([buf], { type: 'image/jpeg' })
  const seq = ++frameSeq
  if (typeof createImageBitmap === 'function' && canvasRef.value?.getContext?.('2d')) {
    createImageBitmap(blob).then(
      (bmp) => {
        if (unmounted || seq !== frameSeq || !canvasRef.value) return bmp.close?.()
        const c = canvasRef.value
        if (c.width !== bmp.width || c.height !== bmp.height) {
          c.width = bmp.width
          c.height = bmp.height
          aspect.value = `${bmp.width} / ${bmp.height}`
        }
        c.getContext('2d').drawImage(bmp, 0, 0)
        bmp.close?.()
        canvasMode.value = true
        hasFrame.value = true
      },
      () => drawWithImg(blob),
    )
    return
  }
  drawWithImg(blob)
}

function revokeCurrent() {
  if (currentUrl) URL.revokeObjectURL(currentUrl)
  currentUrl = null
}

function drawWithImg(blob) {
  if (unmounted || !imgRef.value) return
  const next = URL.createObjectURL(blob)
  const prev = currentUrl
  currentUrl = next
  canvasMode.value = false
  imgRef.value.src = next
  if (prev) URL.revokeObjectURL(prev)
  hasFrame.value = true
}

function onImgLoad() {
  const i = imgRef.value
  if (i?.naturalWidth) aspect.value = `${i.naturalWidth} / ${i.naturalHeight}`
}
function onImgError() {
  revokeCurrent()
  hasFrame.value = false
}

const socket = createLiveViewSocket({
  onFrame,
  onStatus: (m) => {
    if (m?.type === 'status') streamStatus.value = m
  },
})

const shouldRun = computed(
  () => wanted.value && active.value && !hiddenLong.value && camera.connected,
)
watch(
  shouldRun,
  (run) => {
    if (run) socket.start()
    else {
      socket.close()
      clearTimeout(staleTimer)
      stale.value = false
    }
  },
  { immediate: true },
)
watch(
  () => socket.status.value,
  (s) => {
    if (s !== 'open') {
      clearTimeout(staleTimer)
      stale.value = false
    }
  },
)
watch(visible, (v) => {
  clearTimeout(hiddenTimer)
  if (v) hiddenLong.value = false
  else hiddenTimer = setTimeout(() => (hiddenLong.value = true), HIDDEN_CLOSE_MS)
})

onActivated(() => (active.value = true))
onDeactivated(() => (active.value = false))

const state = computed(() => {
  const ss = socket.status.value
  if (!camera.connected) return { key: 'disconnected', label: 'Camera disconnected', tone: 'error' }
  if (ss === 'unauthorized') return { key: 'unauthorized', label: 'Unauthorized', tone: 'error' }
  if (!wanted.value) return { key: 'stopped', label: 'Stopped', tone: 'neutral' }
  if (hiddenLong.value) return { key: 'paused', label: 'Paused: tab hidden', tone: 'warn' }
  if (ss !== 'open') return { key: 'connecting', label: 'Connecting...', tone: 'info' }
  const st = streamStatus.value
  if (!st) return { key: 'connecting', label: 'Connecting...', tone: 'info' }
  if (st.camera_state === 'disconnected')
    return { key: 'disconnected', label: 'Camera disconnected', tone: 'error' }
  if (st.phase === 'waiting') {
    const r = st.reason || st.camera_state
    return { key: 'paused', label: r ? `Paused: ${r}` : 'Paused', tone: 'warn' }
  }
  if (st.phase === 'stopped') return { key: 'stopped', label: 'Stopped', tone: 'neutral' }
  if (stale.value) return { key: 'stale', label: 'No frames', tone: 'warn' }
  return { key: 'live', label: 'Live', tone: 'ok' }
})

const fps = computed(() => {
  const v = streamStatus.value?.fps
  return Number.isFinite(v) ? v.toFixed(1) : null
})
const dropped = computed(() => {
  const s = streamStatus.value
  return s?.client_frames_dropped ?? s?.frames_dropped ?? null
})
const showStale = computed(() => state.value.key === 'stale')
const showPlaceholder = computed(
  () => !hasFrame.value || ['stopped', 'disconnected', 'unauthorized'].includes(state.value.key),
)

async function start() {
  starting.value = true
  try {
    await liveview.start()
    wanted.value = true
  } catch (e) {
    toasts.error(e)
  } finally {
    starting.value = false
  }
}
async function stop() {
  wanted.value = false
  try {
    await liveview.stop()
  } catch (e) {
    toasts.error(e)
  }
}
async function snapshot() {
  snapshotting.value = true
  try {
    const blob = await api.getLiveviewSnapshot({ parseAs: 'blob' })
    downloadBlob(blob, `liveview-${new Date().toISOString().replace(/[:.]/g, '-')}.jpg`)
  } catch (e) {
    toasts.error(e)
  } finally {
    snapshotting.value = false
  }
}

function toggleFullscreen() {
  const el = stageRef.value
  if (!el) return
  if (document.fullscreenElement) document.exitFullscreen?.()
  else el.requestFullscreen?.()
}
const onFsChange = () => (fullscreen.value = document.fullscreenElement === stageRef.value)

onMounted(async () => {
  document.addEventListener('fullscreenchange', onFsChange)
  if (camera.connected) {
    try {
      await liveview.fetchStatus()
      if (liveview.running) wanted.value = true
    } catch {
      /* status is optional; Start still works */
    }
  }
})
onUnmounted(() => {
  unmounted = true
  socket.close()
  clearTimeout(staleTimer)
  clearTimeout(hiddenTimer)
  document.removeEventListener('fullscreenchange', onFsChange)
  revokeCurrent()
})
</script>

<template>
  <section
    class="overflow-hidden rounded-lg border border-camera-border bg-camera-surface"
    aria-label="Live view"
  >
    <header
      class="flex flex-wrap items-center justify-between gap-2 border-b border-camera-border px-4 py-2"
    >
      <div class="flex items-center gap-3">
        <h2 class="font-medium">Live View</h2>
        <UiBadge :tone="state.tone" data-testid="lv-state" aria-live="polite">{{
          state.label
        }}</UiBadge>
        <span v-if="state.key === 'live' && fps" class="text-xs text-camera-muted">
          {{ fps }} fps<template v-if="dropped"> · {{ dropped }} dropped</template>
        </span>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <UiButton
          size="sm"
          :aria-pressed="showGrid"
          :variant="showGrid ? 'primary' : 'secondary'"
          @click="showGrid = !showGrid"
          >Grid</UiButton
        >
        <UiButton
          size="sm"
          :disabled="!camera.connected || !hasFrame"
          aria-label="Toggle fullscreen"
          @click="toggleFullscreen"
          >{{ fullscreen ? 'Exit full' : 'Fullscreen' }}</UiButton
        >
        <UiButton
          size="sm"
          :loading="snapshotting"
          :disabled="!camera.connected"
          data-testid="lv-snapshot"
          @click="snapshot"
          >Snapshot</UiButton
        >
        <UiButton
          v-if="wanted"
          size="sm"
          variant="danger"
          data-testid="lv-stop"
          :disabled="!camera.connected"
          @click="stop"
          >Stop</UiButton
        >
        <UiButton
          v-else
          size="sm"
          variant="primary"
          data-testid="lv-start"
          :loading="starting"
          :disabled="!camera.connected"
          @click="start"
          >Start</UiButton
        >
      </div>
    </header>

    <div
      ref="stageRef"
      class="relative mx-auto flex max-h-[75vh] w-full items-center justify-center bg-black"
      :style="{ aspectRatio: aspect }"
    >
      <img
        v-show="!canvasMode && hasFrame"
        ref="imgRef"
        alt="Camera live view"
        class="h-full w-full object-contain"
        @load="onImgLoad"
        @error="onImgError"
      />
      <canvas
        v-show="canvasMode && hasFrame"
        ref="canvasRef"
        class="h-full w-full object-contain"
        aria-label="Camera live view"
      />
      <div
        v-if="showGrid && hasFrame"
        class="pointer-events-none absolute inset-0"
        data-testid="lv-grid"
        aria-hidden="true"
      >
        <div class="absolute inset-y-0 left-1/3 w-px bg-white/40" />
        <div class="absolute inset-y-0 left-2/3 w-px bg-white/40" />
        <div class="absolute inset-x-0 top-1/3 h-px bg-white/40" />
        <div class="absolute inset-x-0 top-2/3 h-px bg-white/40" />
      </div>
      <div
        v-if="showStale"
        class="absolute inset-0 flex items-center justify-center bg-black/60 text-sm text-camera-warning"
        data-testid="lv-stale"
        role="status"
      >
        No frames received - stream may be stalled
      </div>
      <div
        v-if="showPlaceholder"
        class="absolute inset-0 flex items-center justify-center text-camera-muted"
      >
        <UiEmpty
          v-if="!camera.connected"
          title="Camera not connected"
          hint="Connect the camera to use live view."
        >
          <template #actions>
            <UiButton variant="primary" size="sm" @click="camera.connect().catch(toasts.error)"
              >Connect</UiButton
            >
          </template>
        </UiEmpty>
        <p v-else-if="state.key === 'unauthorized'" class="text-sm">
          Unauthorized - check the API key.
        </p>
        <p v-else class="text-sm">
          {{ wanted ? state.label : 'Press Start to begin live view' }}
        </p>
      </div>
    </div>
  </section>
</template>
