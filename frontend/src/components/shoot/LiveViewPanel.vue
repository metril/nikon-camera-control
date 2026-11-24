<script setup>
import {
  ref,
  nextTick,
  shallowRef,
  computed,
  watch,
  onMounted,
  onActivated,
  onDeactivated,
  onUnmounted,
} from 'vue'
import { api, downloadBlob } from '@/api'
import { createLiveViewSocket } from '@/api/ws.js'
import { useCameraStore } from '@/stores/camera'
import { useAuthStore } from '@/stores/auth'
import { useLiveViewStore } from '@/stores/liveview'
import { useToastsStore } from '@/stores/toasts'
import { useFocusStore } from '@/stores/focus'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import { liveviewPauseReason } from '@/labels'
import { useVisibility } from '@/composables'
import UiButton from '@/components/ui/UiButton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import LiveViewToolbar from './overlays/LiveViewToolbar.vue'
import FocusPill from './overlays/FocusPill.vue'
import HistogramOverlay from './overlays/HistogramOverlay.vue'
import { computeHistogram, computeClipping, computePeaking } from './overlays/analysis.js'
import { drawGrid, drawFocusBrackets, drawLoupe } from './overlays/drawing.js'

const STALE_MS = 3000
const ANALYSIS_WIDTH = 480 // frames are downsampled to this width for histogram, clipping, peaking
const FOCUS_STEP = { small: 50, large: 250 }
const LOCK_MS = 1400
const TAP_SLOP_PX = 8
const HIDDEN_CLOSE_MS = 5000

const camera = useCameraStore()
const auth = useAuthStore()
const liveview = useLiveViewStore()
const toasts = useToastsStore()
const focus = useFocusStore()
const capture = useCaptureStore()
const files = useFilesStore()
const visible = useVisibility()

const imgRef = ref(null)
const canvasRef = ref(null)
const ovcRef = ref(null)
const stageRef = ref(null)
const canvasMode = ref(false)
const fullscreen = ref(false)
const frameSize = ref({ w: 600, h: 400 })
const aspect = computed(() => `${frameSize.value.w} / ${frameSize.value.h}`)
const ratio = computed(() => frameSize.value.w / frameSize.value.h)
const histogram = shallowRef(null)
const focusPt = ref(null) // focus point in frame pixels
const focusState = ref('idle') // idle | moving | locked
const afBusy = ref(false)
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
          frameSize.value = { w: bmp.width, h: bmp.height }
        }
        c.getContext('2d').drawImage(bmp, 0, 0)
        bmp.close?.()
        canvasMode.value = true
        hasFrame.value = true
        markDirty(true)
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
  if (i?.naturalWidth) frameSize.value = { w: i.naturalWidth, h: i.naturalHeight }
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
// A new key (rotated in Settings, or typed into the prompt) needs a fresh handshake; also when
// the same key is re-entered after a 4401 (required flips back to false).
watch(
  () => [auth.apiKey, auth.required],
  ([key, required], [prevKey, prevRequired]) => {
    if (!shouldRun.value) return
    if (key !== prevKey || (prevRequired && !required)) socket.restart()
  },
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
  if (ss === 'forbidden') return { key: 'forbidden', label: 'Origin not allowed', tone: 'error' }
  if (ss === 'unauthorized') return { key: 'unauthorized', label: 'Unauthorized', tone: 'error' }
  if (!wanted.value) return { key: 'stopped', label: 'Stopped', tone: 'neutral' }
  if (hiddenLong.value) return { key: 'paused', label: 'Paused: tab hidden', tone: 'warn' }
  if (ss !== 'open') return { key: 'connecting', label: 'Connecting…', tone: 'info' }
  const st = streamStatus.value
  if (!st) return { key: 'connecting', label: 'Connecting…', tone: 'info' }
  if (st.camera_state === 'disconnected')
    return { key: 'disconnected', label: 'Camera disconnected', tone: 'error' }
  if (st.phase === 'waiting') {
    const r = st.reason || st.camera_state
    return {
      key: 'paused',
      label: r ? `Paused: ${liveviewPauseReason(r)}` : 'Paused',
      tone: 'warn',
    }
  }
  if (st.phase === 'stopped') return { key: 'stopped', label: 'Stopped', tone: 'neutral' }
  if (stale.value) return { key: 'stale', label: 'No frames', tone: 'warn' }
  return { key: 'live', label: 'Live', tone: 'ok' }
})

const fps = computed(() => {
  const v = streamStatus.value?.fps
  return Number.isFinite(v) && v > 0 ? v.toFixed(1) : null
})
const dropped = computed(() => {
  const s = streamStatus.value
  return s?.client_frames_dropped ?? s?.frames_dropped ?? null
})
const badgeLabel = computed(() => {
  if (state.value.key !== 'live') return state.value.label
  if (focusState.value === 'moving') return 'Focusing…'
  if (focusState.value === 'locked') return 'Focus locked'
  return fps.value ? `Live · ${fps.value} fps` : 'Live'
})
const badgeDot = computed(() => {
  if (state.value.key === 'live')
    return focusState.value === 'idle' ? 'bg-camera-danger animate-pulse' : 'bg-camera-accent'
  return state.value.tone === 'warn' ? 'bg-camera-warn' : 'bg-camera-faint'
})
const showStale = computed(() => state.value.key === 'stale')
const showPlaceholder = computed(
  () =>
    !hasFrame.value ||
    ['stopped', 'disconnected', 'unauthorized', 'forbidden'].includes(state.value.key),
)

// Keep keyboard focus on the control that replaces the one just used.
async function refocus(id) {
  await nextTick()
  stageRef.value?.querySelector(`[data-testid="${id}"]`)?.focus()
}
async function start() {
  starting.value = true
  try {
    await liveview.start()
    wanted.value = true
    refocus('lv-stop')
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
    refocus('lv-start')
  } catch (e) {
    toasts.error(e)
  }
}
// ---- Overlays: analysis runs on a downsampled copy of the decoded frame, throttled to stream fps.
let raf = 0
let lastDraw = 0
let analysisStale = true
let needsDraw = false
let ovCtx = null
let small = null
let smallCtx = null
let clipMask = null
let peakMask = null
let maskCtxs = {}
let onionImg = null
let releaseOnion = null
let lockTimer = null
let loupePt = null
let down = null

const tools = computed(() => liveview.tools)
const streamFps = computed(() => Math.min(60, Math.max(1, Number(streamStatus.value?.fps) || 12)))

function markDirty(newFrame = false) {
  if (newFrame) analysisStale = true
  needsDraw = true
  if (raf || unmounted || typeof requestAnimationFrame !== 'function') return
  raf = requestAnimationFrame(tick)
}
function tick(now) {
  raf = 0
  if (!needsDraw || unmounted) return
  // New frames and tool changes are paced by the stream fps; pointer-only redraws are cheap.
  const gap = analysisStale ? 1000 / streamFps.value : 16
  if (now - lastDraw < gap) {
    raf = requestAnimationFrame(tick)
    return
  }
  lastDraw = now
  needsDraw = false
  renderOverlays()
}
function getCtx(canvas) {
  return canvas?.getContext?.('2d', { willReadFrequently: true }) || null
}
function maskCanvas(key, mask, w, h) {
  let c = maskCtxs[key]?.canvas
  if (!c || c.width !== w || c.height !== h) {
    c = document.createElement('canvas')
    c.width = w
    c.height = h
    maskCtxs[key] = c.getContext('2d')
  }
  maskCtxs[key].putImageData(new ImageData(mask, w, h), 0, 0)
  return c
}
function analyse(main) {
  analysisStale = false
  const t = tools.value
  if (!main || !main.width) {
    histogram.value = null
    clipMask = peakMask = null
    return
  }
  const w = Math.min(ANALYSIS_WIDTH, main.width)
  const h = Math.max(1, Math.round((w * main.height) / main.width))
  if (!small) small = document.createElement('canvas')
  if (small.width !== w || small.height !== h) {
    small.width = w
    small.height = h
    smallCtx = getCtx(small)
  }
  if (!smallCtx) return
  smallCtx.drawImage(main, 0, 0, w, h)
  const img = smallCtx.getImageData(0, 0, w, h)
  histogram.value = t.hist ? computeHistogram(img) : null
  clipMask = t.clip ? maskCanvas('clip', computeClipping(img), w, h) : null
  peakMask = t.peak ? maskCanvas('peak', computePeaking(img), w, h) : null
}
function renderOverlays() {
  const o = ovcRef.value
  if (!o) return
  if (!ovCtx || ovCtx.canvas !== o) ovCtx = o.getContext?.('2d') || null
  const ctx = ovCtx
  if (!ctx) return
  const { w, h } = frameSize.value
  ctx.clearRect(0, 0, o.width, o.height)
  const t = tools.value
  const main = canvasMode.value && hasFrame.value ? canvasRef.value : null
  if (analysisStale) analyse(main)
  if (t.onion && onionImg) {
    ctx.globalAlpha = 0.38
    ctx.drawImage(onionImg, 0, 0, w, h)
    ctx.globalAlpha = 1
  }
  ctx.imageSmoothingEnabled = false
  if (clipMask) ctx.drawImage(clipMask, 0, 0, w, h)
  if (peakMask) ctx.drawImage(peakMask, 0, 0, w, h)
  drawGrid(ctx, t.grid, w, h)
  if (focusPt.value) drawFocusBrackets(ctx, focusPt.value, w, focusState.value)
  if (t.loupe && main) drawLoupe(ctx, main, loupePt || { x: w / 2, y: h / 2 }, w)
}

watch(tools, () => markDirty(true), { deep: true })
watch([focusPt, focusState, frameSize], () => markDirty())

// ---- Last shot overlay: newest captured image, read from the capture and files stores.
const isImage = (f) =>
  f && (f.kind === 'image' || (!f.kind && /\.(jpe?g|png)$/i.test(f.name || f.path || '')))
const lastShotPath = computed(
  () =>
    (
      capture.lastFiles?.find?.(isImage) ??
      capture.lastCapture?.files?.find?.(isImage) ??
      files.items.find(isImage)
    )?.path ?? null,
)
async function loadOnion() {
  releaseOnion?.()
  releaseOnion = null
  onionImg = null
  if (!tools.value.onion || !lastShotPath.value) return
  const path = lastShotPath.value
  try {
    const h = await files.acquireThumbnail(path)
    if (unmounted || path !== lastShotPath.value || !tools.value.onion) return h.release()
    const im = new Image()
    im.onload = () => {
      onionImg = im
      markDirty()
    }
    releaseOnion = h.release
    im.src = h.url
  } catch {
    /* overlay is optional */
  }
}
watch([lastShotPath, () => tools.value.onion], ([path, on], [, wasOn]) => {
  if (on && !wasOn && !path)
    toasts.info('Take a photo first. The overlay shows your last shot over live view.')
  loadOnion()
})

// ---- Focus: tapping sets the focus point and runs autofocus; the pill drives manual steps.
const frameFocused = () => camera.connected && !!hasFrame.value
let pointUnsupported = false // the body can't move its AF point: skip setPoint this session
async function runAutofocus(move = false) {
  if (!camera.connected) return
  clearTimeout(lockTimer)
  const { w, h } = frameSize.value
  if (!focusPt.value) focusPt.value = { x: w / 2, y: h / 2 }
  focusState.value = 'moving'
  afBusy.value = true
  try {
    if (move && !pointUnsupported) {
      try {
        await focus.setPoint(focusPt.value.x / (w || 1), focusPt.value.y / (h || 1))
      } catch (e) {
        if (e?.status === 501 || e?.code === 'FEATURE_UNSUPPORTED') pointUnsupported = true
        toasts.warn('Could not move the focus point. Focusing at the camera’s current point.')
      }
    }
    const r = await focus.autofocus()
    if (r?.focused === false) {
      focusState.value = 'idle'
      toasts.warn('Autofocus could not lock. Try another spot or focus by hand.')
    } else {
      focusState.value = 'locked'
      lockTimer = setTimeout(() => (focusState.value = 'idle'), LOCK_MS)
    }
  } catch (e) {
    focusState.value = 'idle'
    toasts.error(e)
  } finally {
    afBusy.value = false
  }
}
async function focusStep(dir, size) {
  let n = dir * FOCUS_STEP[size]
  const r = focus.status?.range
  if (r) n = Math.max(r.min, Math.min(r.max, n))
  try {
    await focus.manual(n)
  } catch (e) {
    toasts.error(e)
  }
}

// ---- Pointer: tap or click focuses; the loupe follows the mouse and is dragged on touch.
function framePoint(e) {
  const r = ovcRef.value.getBoundingClientRect()
  const { w, h } = frameSize.value
  return {
    x: Math.max(0, Math.min(w, ((e.clientX - r.left) / (r.width || 1)) * w)),
    y: Math.max(0, Math.min(h, ((e.clientY - r.top) / (r.height || 1)) * h)),
  }
}
function onPointerDown(e) {
  down = { cx: e.clientX, cy: e.clientY, moved: false }
  ovcRef.value?.setPointerCapture?.(e.pointerId)
  if (tools.value.loupe && e.pointerType !== 'mouse') {
    loupePt = framePoint(e)
    markDirty()
  }
}
function onPointerMove(e) {
  if (down && Math.hypot(e.clientX - down.cx, e.clientY - down.cy) > TAP_SLOP_PX) down.moved = true
  if (tools.value.loupe && (down || e.pointerType === 'mouse')) {
    loupePt = framePoint(e)
    markDirty()
  }
}
function onPointerUp(e) {
  const tap = down && !down.moved
  down = null
  if (tap && frameFocused()) {
    focusPt.value = framePoint(e)
    runAutofocus(true)
  }
}
function onPointerCancel() {
  down = null
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
  if (raf && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(raf)
  clearTimeout(lockTimer)
  releaseOnion?.()
  socket.close()
  clearTimeout(staleTimer)
  clearTimeout(hiddenTimer)
  document.removeEventListener('fullscreenchange', onFsChange)
  revokeCurrent()
})
</script>

<template>
  <section
    ref="stageRef"
    class="lv-stage overflow-hidden rounded-card border border-camera-subtle bg-black"
    aria-label="Live view"
  >
    <div class="lv-frame" :style="{ '--ar': aspect, '--arn': ratio }">
      <img
        v-show="!canvasMode && hasFrame"
        ref="imgRef"
        alt="Camera live view"
        class="absolute inset-0 h-full w-full object-contain"
        @load="onImgLoad"
        @error="onImgError"
      />
      <canvas
        v-show="canvasMode && hasFrame"
        ref="canvasRef"
        class="absolute inset-0 h-full w-full"
        aria-label="Camera live view"
      />
      <canvas
        v-if="hasFrame && camera.connected"
        ref="ovcRef"
        :width="frameSize.w"
        :height="frameSize.h"
        class="lv-overlay absolute inset-0 h-full w-full"
        data-testid="lv-overlay"
        aria-hidden="true"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerCancel"
      />
      <div
        v-if="showStale"
        class="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/60 text-sm text-camera-warn"
        data-testid="lv-stale"
        role="status"
      >
        No frames received. The stream may be stalled.
      </div>
      <div
        v-if="showPlaceholder"
        class="absolute inset-0 grid place-items-center overflow-auto bg-camera-surface p-4"
        data-testid="lv-placeholder"
      >
        <UiEmpty
          :title="
            !camera.connected
              ? 'Camera not connected'
              : state.key === 'forbidden'
                ? 'Origin not allowed'
                : state.key === 'unauthorized'
                  ? 'Unauthorized'
                  : wanted
                    ? state.label
                    : 'Live view is off'
          "
          :hint="
            !camera.connected
              ? 'Connect the camera to use live view.'
              : state.key === 'forbidden'
                ? 'This page\'s origin is not allowed by the server. Add it under Settings › General › Allowed origins.'
                : state.key === 'unauthorized'
                  ? 'Check the API key.'
                  : wanted
                    ? ''
                    : 'Start live view to frame your shot.'
          "
        >
          <template #actions>
            <UiButton
              v-if="!camera.connected"
              variant="primary"
              size="sm"
              @click="camera.connect().catch(toasts.error)"
              >Connect</UiButton
            >
            <UiButton
              v-if="!wanted && state.key !== 'forbidden' && state.key !== 'unauthorized'"
              :variant="camera.connected ? 'primary' : 'secondary'"
              size="sm"
              data-testid="lv-start"
              :loading="starting"
              :disabled="!camera.connected"
              @click="start"
              >Start live view</UiButton
            >
          </template>
        </UiEmpty>
      </div>

      <div class="lv-top">
        <LiveViewToolbar v-if="!showPlaceholder" class="min-w-0" />
      </div>

      <div
        v-if="wanted && camera.connected"
        class="lv-pill lv-actions"
        role="toolbar"
        aria-label="Live view actions"
      >
        <button
          v-if="hasFrame"
          type="button"
          data-testid="lv-snapshot"
          :disabled="snapshotting"
          aria-label="Snapshot"
          title="Snapshot"
          @click="snapshot"
        >
          <UiIcon name="Download" :size="16" />
        </button>
        <button
          v-if="hasFrame"
          type="button"
          data-testid="lv-fullscreen"
          :aria-label="fullscreen ? 'Exit fullscreen' : 'Fullscreen'"
          :title="fullscreen ? 'Exit fullscreen' : 'Fullscreen'"
          @click="toggleFullscreen"
        >
          <UiIcon :name="fullscreen ? 'Minimize' : 'Maximize'" :size="16" />
        </button>
        <button
          type="button"
          class="stop"
          data-testid="lv-stop"
          aria-label="Stop live view"
          title="Stop live view"
          @click="stop"
        >
          <UiIcon name="Square" :size="16" />
        </button>
      </div>

      <div v-if="wanted && camera.connected" class="lv-badge" aria-live="polite">
        <i class="h-1.5 w-1.5 rounded-full" :class="badgeDot" />
        <span data-testid="lv-state" class="tabular-nums">{{ badgeLabel }}</span>
        <span v-if="state.key === 'live' && dropped" class="tabular-nums text-camera-muted"
          >· {{ dropped }} dropped</span
        >
      </div>
      <div v-if="!showPlaceholder" class="lv-focuswrap">
        <FocusPill
          :disabled="!camera.connected"
          :busy="afBusy"
          @step="focusStep"
          @autofocus="runAutofocus()"
        />
      </div>
      <div v-if="!showPlaceholder && tools.hist" class="lv-histwrap">
        <HistogramOverlay :histogram="histogram" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.lv-stage {
  display: block;
}
.lv-stage:fullscreen {
  display: grid;
  place-items: center;
  height: 100%;
  border: 0;
  border-radius: 0;
}
.lv-frame {
  position: relative;
  width: 100%;
  margin: 0 auto;
  aspect-ratio: var(--ar);
  container: lv / inline-size;
  background: #000;
}
.lv-stage:fullscreen .lv-frame {
  width: min(100vw, calc(100vh * var(--arn)));
}
.lv-overlay {
  cursor: crosshair;
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
}
.lv-top {
  position: absolute;
  top: 10px;
  left: 10px;
  /* leave room for the three action buttons on the right */
  right: calc(18px + 3 * var(--ctl-sm) + 12px);
  display: flex;
  align-items: flex-start;
  gap: 8px;
  pointer-events: none;
}
.lv-top > * {
  pointer-events: auto;
}
.lv-actions {
  position: absolute;
  top: 10px;
  right: 10px;
}
.lv-pill {
  display: flex;
  flex: none;
  gap: 2px;
  padding: 3px;
  border-radius: 9999px;
  background: theme('colors.camera.overlay');
  border: 1px solid theme('colors.camera.border');
  backdrop-filter: blur(6px);
}
.lv-pill button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--ctl-sm);
  height: var(--ctl-sm);
  border-radius: 9999px;
  border: 0;
  background: none;
  color: theme('colors.camera.muted');
  cursor: pointer;
  transition:
    background-color 0.12s,
    color 0.12s;
}
.lv-pill button:hover:not(:disabled) {
  color: theme('colors.camera.text');
}
.lv-pill button:active:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
}
.lv-pill button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.lv-pill .stop {
  color: theme('colors.camera.danger');
}
html[data-layout='touch'] .lv-pill button {
  width: 44px;
  height: 44px;
}
.lv-badge {
  position: absolute;
  bottom: 12px;
  left: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  border-radius: 9999px;
  background: theme('colors.camera.overlay');
  border: 1px solid theme('colors.camera.border');
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  pointer-events: none;
}
.lv-focuswrap {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
}
.lv-histwrap {
  position: absolute;
  right: 12px;
  bottom: 12px;
}
/* Narrower frames: the focus pill moves left and lifts above the Live badge (never overlapping) */
@container lv (max-width: 720px) {
  .lv-focuswrap {
    left: 12px;
    transform: none;
    bottom: 50px;
  }
}
/* Narrow frames: the action pill drops to the bottom-right, the histogram sits above it */
@container lv (max-width: 640px) {
  .lv-top {
    right: 10px;
  }
  .lv-actions {
    top: auto;
    bottom: 12px;
  }
  .lv-histwrap {
    bottom: calc(12px + var(--ctl-sm) + 14px);
  }
}
@container lv (max-width: 420px) {
  .lv-focuswrap {
    bottom: calc(12px + var(--ctl-sm) + 14px);
  }
  .lv-histwrap {
    display: none;
  }
}
</style>
