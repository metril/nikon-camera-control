<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()
const canvasRef = ref(null)
const containerRef = ref(null)
const showGrid = ref(false)
const fps = ref(0)
const frameCount = ref(0)

let ws = null
let ctx = null
let lastFrameTime = 0
let fpsWindow = []

// Connect to live view WebSocket
function connectLiveView() {
  if (!camera.connected) return

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/ws/liveview`

  ws = new WebSocket(wsUrl)
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => {
    camera.liveViewActive = true
    console.log('Live view connected')
  }

  ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      displayFrame(event.data)
    } else {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'status') {
          fps.value = data.data.fps_actual || 0
        }
      } catch (e) {
        // Binary frame
      }
    }
  }

  ws.onclose = () => {
    camera.liveViewActive = false
    console.log('Live view disconnected')
  }

  ws.onerror = (error) => {
    console.error('Live view error:', error)
  }
}

function disconnectLiveView() {
  if (ws) {
    ws.close()
    ws = null
  }
  camera.liveViewActive = false
}

function displayFrame(arrayBuffer) {
  if (!canvasRef.value || !ctx) return

  const blob = new Blob([arrayBuffer], { type: 'image/jpeg' })
  const url = URL.createObjectURL(blob)
  const img = new Image()

  img.onload = () => {
    // Resize canvas to match image aspect ratio
    const canvas = canvasRef.value
    const container = containerRef.value

    if (!canvas || !container) return

    const containerWidth = container.clientWidth
    const containerHeight = container.clientHeight
    const imgAspect = img.width / img.height
    const containerAspect = containerWidth / containerHeight

    let drawWidth, drawHeight

    if (imgAspect > containerAspect) {
      drawWidth = containerWidth
      drawHeight = containerWidth / imgAspect
    } else {
      drawHeight = containerHeight
      drawWidth = containerHeight * imgAspect
    }

    canvas.width = drawWidth
    canvas.height = drawHeight

    // Draw image
    ctx.drawImage(img, 0, 0, drawWidth, drawHeight)

    // Draw grid overlay if enabled
    if (showGrid.value) {
      drawGrid(drawWidth, drawHeight)
    }

    URL.revokeObjectURL(url)
    frameCount.value++

    // Calculate FPS
    const now = performance.now()
    fpsWindow.push(now)
    fpsWindow = fpsWindow.filter(t => now - t < 1000)
    fps.value = fpsWindow.length
  }

  img.src = url
}

function drawGrid(width, height) {
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)'
  ctx.lineWidth = 1

  // Rule of thirds
  const thirdW = width / 3
  const thirdH = height / 3

  ctx.beginPath()
  // Vertical lines
  ctx.moveTo(thirdW, 0)
  ctx.lineTo(thirdW, height)
  ctx.moveTo(thirdW * 2, 0)
  ctx.lineTo(thirdW * 2, height)
  // Horizontal lines
  ctx.moveTo(0, thirdH)
  ctx.lineTo(width, thirdH)
  ctx.moveTo(0, thirdH * 2)
  ctx.lineTo(width, thirdH * 2)
  ctx.stroke()
}

function toggleLiveView() {
  if (camera.liveViewActive) {
    disconnectLiveView()
  } else {
    connectLiveView()
  }
}

watch(() => camera.connected, (connected) => {
  if (!connected && ws) {
    disconnectLiveView()
  }
})

onMounted(() => {
  if (canvasRef.value) {
    ctx = canvasRef.value.getContext('2d')
  }
})

onUnmounted(() => {
  disconnectLiveView()
})
</script>

<template>
  <div class="bg-camera-surface border border-camera-border rounded-lg overflow-hidden">
    <!-- Live view header -->
    <div class="flex items-center justify-between px-4 py-2 border-b border-camera-border">
      <div class="flex items-center gap-3">
        <h2 class="font-medium">Live View</h2>
        <span
          v-if="camera.liveViewActive"
          class="flex items-center gap-1.5 text-xs text-camera-success"
        >
          <span class="w-2 h-2 bg-camera-success rounded-full recording-dot"></span>
          {{ fps }} FPS
        </span>
      </div>
      <div class="flex items-center gap-2">
        <button
          @click="showGrid = !showGrid"
          class="px-3 py-1 text-sm rounded transition-colors"
          :class="showGrid ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-text hover:bg-camera-border/80'"
        >
          Grid
        </button>
        <button
          @click="toggleLiveView"
          :disabled="!camera.connected"
          class="px-3 py-1 text-sm rounded transition-colors"
          :class="camera.liveViewActive
            ? 'bg-camera-error text-white hover:bg-camera-error/80'
            : 'bg-camera-accent text-white hover:bg-camera-accent/80 disabled:opacity-50 disabled:cursor-not-allowed'"
        >
          {{ camera.liveViewActive ? 'Stop' : 'Start' }}
        </button>
      </div>
    </div>

    <!-- Canvas container -->
    <div
      ref="containerRef"
      class="relative bg-black flex items-center justify-center"
      style="aspect-ratio: 16 / 9; min-height: 300px;"
    >
      <!-- Canvas -->
      <canvas
        ref="canvasRef"
        class="live-view-canvas max-w-full max-h-full"
      ></canvas>

      <!-- Placeholder when not streaming -->
      <div
        v-if="!camera.liveViewActive"
        class="absolute inset-0 flex flex-col items-center justify-center text-camera-muted"
      >
        <svg class="w-16 h-16 mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
        <p v-if="camera.connected">Click "Start" to begin live view</p>
        <p v-else>Connect camera to enable live view</p>
      </div>
    </div>
  </div>
</template>
