<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()

// Configuration state
const intervalSeconds = ref(5)
const totalFrames = ref(100)
const useFrameCount = ref(true) // true = frame count, false = duration
const durationMinutes = ref(10)

// Session state
const status = ref({
  state: 'idle',
  frames_captured: 0,
  total_frames: 0,
  interval_seconds: 0,
  elapsed_seconds: 0,
  estimated_remaining_seconds: 0,
})
const diskEstimate = ref(null)
const configSummary = ref(null)

// Video generation
const videoFps = ref(24)
const videoCodec = ref('h264')
const videoQuality = ref('high')
const isGenerating = ref(false)

// UI state
const isConfiguring = ref(false)
const error = ref(null)
const showVideoOptions = ref(false)

const isRunning = computed(() => status.value.state === 'running')
const isPaused = computed(() => status.value.state === 'paused')
const isIdle = computed(() => ['idle', 'completed', 'cancelled', 'error'].includes(status.value.state))
const hasFrames = computed(() => status.value.frames_captured > 0)

const progressPercent = computed(() => {
  if (status.value.total_frames === 0) return 0
  return Math.round((status.value.frames_captured / status.value.total_frames) * 100)
})

const computedTotalFrames = computed(() => {
  if (useFrameCount.value) {
    return totalFrames.value
  }
  return Math.floor((durationMinutes.value * 60) / intervalSeconds.value)
})

const estimatedDuration = computed(() => {
  const totalSecs = computedTotalFrames.value * intervalSeconds.value
  const hours = Math.floor(totalSecs / 3600)
  const mins = Math.floor((totalSecs % 3600) / 60)
  const secs = totalSecs % 60
  if (hours > 0) return `${hours}h ${mins}m`
  if (mins > 0) return `${mins}m ${secs}s`
  return `${secs}s`
})

const estimatedVideoDuration = computed(() => {
  const frames = computedTotalFrames.value
  const secs = frames / videoFps.value
  if (secs >= 60) {
    const mins = Math.floor(secs / 60)
    const remaining = Math.round(secs % 60)
    return `${mins}m ${remaining}s`
  }
  return `${secs.toFixed(1)}s`
})

function formatTime(seconds) {
  if (!seconds || seconds <= 0) return '--'
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`
  if (mins > 0) return `${mins}m ${secs}s`
  return `${secs}s`
}

async function fetchStatus() {
  try {
    const response = await fetch('/api/timelapse/status')
    if (response.ok) {
      status.value = await response.json()
    }
  } catch (e) {
    console.error('Failed to fetch timelapse status:', e)
  }
}

async function estimateDiskSpace() {
  try {
    const response = await fetch('/api/timelapse/estimate-disk-space', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        total_frames: computedTotalFrames.value,
        format_type: 'raw'
      })
    })
    if (response.ok) {
      diskEstimate.value = await response.json()
    }
  } catch (e) {
    console.error('Failed to estimate disk space:', e)
  }
}

async function configure() {
  isConfiguring.value = true
  error.value = null

  try {
    const payload = {
      interval_seconds: intervalSeconds.value,
    }

    if (useFrameCount.value) {
      payload.total_frames = totalFrames.value
    } else {
      payload.duration_seconds = durationMinutes.value * 60
    }

    const response = await fetch('/api/timelapse/configure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Configuration failed')
    }

    configSummary.value = await response.json()
    await estimateDiskSpace()
  } catch (e) {
    error.value = e.message
  } finally {
    isConfiguring.value = false
  }
}

async function start() {
  error.value = null

  // Configure first if not already done
  if (!configSummary.value) {
    await configure()
    if (error.value) return
  }

  try {
    const response = await fetch('/api/timelapse/start', { method: 'POST' })
    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Failed to start')
    }
    status.value = await response.json()
  } catch (e) {
    error.value = e.message
  }
}

async function stop() {
  try {
    const response = await fetch('/api/timelapse/stop', { method: 'POST' })
    if (response.ok) {
      status.value = await response.json()
    }
  } catch (e) {
    error.value = e.message
  }
}

async function pause() {
  try {
    const response = await fetch('/api/timelapse/pause', { method: 'POST' })
    if (response.ok) {
      status.value = await response.json()
    }
  } catch (e) {
    error.value = e.message
  }
}

async function resume() {
  try {
    const response = await fetch('/api/timelapse/resume', { method: 'POST' })
    if (response.ok) {
      status.value = await response.json()
    }
  } catch (e) {
    error.value = e.message
  }
}

async function generateVideo() {
  isGenerating.value = true
  error.value = null

  try {
    const response = await fetch('/api/timelapse/generate-video', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fps: videoFps.value,
        codec: videoCodec.value,
        quality: videoQuality.value
      })
    })

    if (!response.ok) {
      const data = await response.json()
      throw new Error(data.detail || 'Video generation failed')
    }

    const result = await response.json()
    alert(`Video generated: ${result.video_path}`)
  } catch (e) {
    error.value = e.message
  } finally {
    isGenerating.value = false
  }
}

// Poll for status updates when running
let statusInterval = null
watch(isRunning, (running) => {
  if (running) {
    statusInterval = setInterval(fetchStatus, 1000)
  } else if (statusInterval) {
    clearInterval(statusInterval)
    statusInterval = null
  }
})

// Also watch for paused state
watch(isPaused, (paused) => {
  if (paused && statusInterval) {
    clearInterval(statusInterval)
    statusInterval = null
  }
})

onMounted(() => {
  fetchStatus()
})

onUnmounted(() => {
  if (statusInterval) {
    clearInterval(statusInterval)
  }
})
</script>

<template>
  <div class="bg-camera-surface border border-camera-border rounded-lg overflow-hidden">
    <div class="px-4 py-2 border-b border-camera-border flex items-center justify-between">
      <h2 class="font-medium">Time-lapse</h2>
      <span
        class="text-xs px-2 py-0.5 rounded"
        :class="{
          'bg-camera-success/20 text-camera-success': isRunning,
          'bg-camera-warning/20 text-camera-warning': isPaused,
          'bg-camera-border text-camera-muted': isIdle
        }"
      >
        {{ status.state }}
      </span>
    </div>

    <div class="p-4 space-y-4">
      <!-- Error Message -->
      <div v-if="error" class="p-3 bg-camera-error/10 border border-camera-error/30 rounded text-sm text-camera-error">
        {{ error }}
      </div>

      <!-- Configuration (when idle) -->
      <div v-if="isIdle" class="space-y-4">
        <!-- Interval -->
        <div>
          <label class="block text-sm text-camera-muted mb-1">Interval (seconds)</label>
          <input
            v-model.number="intervalSeconds"
            type="number"
            min="1"
            max="3600"
            class="w-full px-3 py-2 bg-camera-bg border border-camera-border rounded text-sm focus:outline-none focus:border-camera-accent"
          />
          <p class="text-xs text-camera-muted mt-1">Min 2s for RAW, 1s for JPEG</p>
        </div>

        <!-- Mode Toggle -->
        <div class="flex gap-2">
          <button
            @click="useFrameCount = true"
            class="flex-1 px-3 py-2 text-sm rounded transition-colors"
            :class="useFrameCount ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-text'"
          >
            Frame Count
          </button>
          <button
            @click="useFrameCount = false"
            class="flex-1 px-3 py-2 text-sm rounded transition-colors"
            :class="!useFrameCount ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-text'"
          >
            Duration
          </button>
        </div>

        <!-- Frame Count / Duration Input -->
        <div v-if="useFrameCount">
          <label class="block text-sm text-camera-muted mb-1">Total Frames</label>
          <input
            v-model.number="totalFrames"
            type="number"
            min="1"
            max="10000"
            class="w-full px-3 py-2 bg-camera-bg border border-camera-border rounded text-sm focus:outline-none focus:border-camera-accent"
          />
        </div>
        <div v-else>
          <label class="block text-sm text-camera-muted mb-1">Duration (minutes)</label>
          <input
            v-model.number="durationMinutes"
            type="number"
            min="1"
            max="1440"
            class="w-full px-3 py-2 bg-camera-bg border border-camera-border rounded text-sm focus:outline-none focus:border-camera-accent"
          />
        </div>

        <!-- Summary -->
        <div class="p-3 bg-camera-bg rounded text-sm space-y-1">
          <div class="flex justify-between">
            <span class="text-camera-muted">Frames:</span>
            <span>{{ computedTotalFrames }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-camera-muted">Capture Duration:</span>
            <span>{{ estimatedDuration }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-camera-muted">Video @ {{ videoFps }}fps:</span>
            <span>{{ estimatedVideoDuration }}</span>
          </div>
          <div v-if="diskEstimate" class="flex justify-between">
            <span class="text-camera-muted">Est. Disk Space:</span>
            <span>~{{ diskEstimate.total_gb }} GB</span>
          </div>
        </div>

        <!-- Start Button -->
        <button
          @click="start"
          :disabled="!camera.connected || isConfiguring"
          class="w-full py-3 bg-camera-accent text-white font-medium rounded hover:bg-camera-accent/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {{ isConfiguring ? 'Configuring...' : 'Start Time-lapse' }}
        </button>
      </div>

      <!-- Progress (when running/paused) -->
      <div v-else class="space-y-4">
        <!-- Progress Bar -->
        <div>
          <div class="flex justify-between text-sm mb-1">
            <span>{{ status.frames_captured }} / {{ status.total_frames }} frames</span>
            <span>{{ progressPercent }}%</span>
          </div>
          <div class="w-full h-3 bg-camera-border rounded-full overflow-hidden">
            <div
              class="h-full bg-camera-accent transition-all duration-300"
              :style="{ width: `${progressPercent}%` }"
            ></div>
          </div>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-2 gap-3 text-sm">
          <div class="p-2 bg-camera-bg rounded">
            <span class="text-camera-muted">Elapsed</span>
            <p class="font-medium">{{ formatTime(status.elapsed_seconds) }}</p>
          </div>
          <div class="p-2 bg-camera-bg rounded">
            <span class="text-camera-muted">Remaining</span>
            <p class="font-medium">{{ formatTime(status.estimated_remaining_seconds) }}</p>
          </div>
        </div>

        <!-- Controls -->
        <div class="flex gap-2">
          <button
            v-if="isRunning"
            @click="pause"
            class="flex-1 py-2 bg-camera-warning text-white rounded hover:bg-camera-warning/80 transition-colors"
          >
            Pause
          </button>
          <button
            v-if="isPaused"
            @click="resume"
            class="flex-1 py-2 bg-camera-accent text-white rounded hover:bg-camera-accent/80 transition-colors"
          >
            Resume
          </button>
          <button
            @click="stop"
            class="flex-1 py-2 bg-camera-error text-white rounded hover:bg-camera-error/80 transition-colors"
          >
            Stop
          </button>
        </div>
      </div>

      <!-- Video Generation (when has frames) -->
      <div v-if="hasFrames && isIdle" class="border-t border-camera-border pt-4">
        <button
          @click="showVideoOptions = !showVideoOptions"
          class="flex items-center justify-between w-full text-sm"
        >
          <span class="font-medium">Generate Video</span>
          <svg
            class="w-4 h-4 transition-transform"
            :class="showVideoOptions ? 'rotate-180' : ''"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        <div v-if="showVideoOptions" class="mt-3 space-y-3">
          <div class="grid grid-cols-3 gap-2">
            <div>
              <label class="block text-xs text-camera-muted mb-1">FPS</label>
              <select v-model.number="videoFps" class="w-full px-2 py-1 bg-camera-bg border border-camera-border rounded text-sm">
                <option :value="24">24</option>
                <option :value="30">30</option>
                <option :value="60">60</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-camera-muted mb-1">Codec</label>
              <select v-model="videoCodec" class="w-full px-2 py-1 bg-camera-bg border border-camera-border rounded text-sm">
                <option value="h264">H.264</option>
                <option value="h265">H.265</option>
                <option value="prores">ProRes</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-camera-muted mb-1">Quality</label>
              <select v-model="videoQuality" class="w-full px-2 py-1 bg-camera-bg border border-camera-border rounded text-sm">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
          </div>

          <button
            @click="generateVideo"
            :disabled="isGenerating"
            class="w-full py-2 bg-camera-accent text-white rounded hover:bg-camera-accent/80 disabled:opacity-50 transition-colors"
          >
            {{ isGenerating ? 'Generating...' : 'Generate Video' }}
          </button>
        </div>
      </div>

      <!-- Jitter Warning -->
      <p class="text-xs text-camera-muted">
        Note: Software intervalometer has ~500ms jitter per frame
      </p>
    </div>
  </div>
</template>
