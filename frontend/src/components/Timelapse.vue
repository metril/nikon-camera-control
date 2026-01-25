<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()

// Configuration state
const intervalSeconds = ref(5)
const totalFrames = ref(100)
const useFrameCount = ref(true)
const durationMinutes = ref(10)

// Bracketing configuration
const bracketEnabled = ref(false)
const bracketMode = ref('quick')  // 'quick' or 'advanced'
const bracketPresets = ref({})
const multiBracketPresets = ref({})

// Quick setup state - independent toggles for each bracket type
const exposureEnabled = ref(false)
const exposureValues = ref(['-2', '0', '+2'])
const isoEnabled = ref(false)
const isoValues = ref(['100', '400', '1600'])
const apertureEnabled = ref(false)
const apertureValues = ref(['2.8', '5.6', '11'])
const shutterEnabled = ref(false)
const shutterValues = ref(['1/250', '1/125', '1/60'])
const combineMode = ref('sequence')  // 'sequence' or 'paired'

// Advanced mode state - explicit shot list
const advancedSteps = ref([])
const selectedPreset = ref('')
const expandedSteps = ref(new Set())  // Track which steps are expanded

// Generated preview
const generatedSteps = ref([])

// Session state
const status = ref({
  state: 'idle',
  frames_captured: 0,
  bracket_sets_captured: 0,
  total_frames: 0,
  interval_seconds: 0,
  elapsed_seconds: 0,
  estimated_remaining_seconds: 0,
  bracketing: { enabled: false, bracket_type: 'exposure', shots_per_bracket: 1 }
})
const diskEstimate = ref(null)
const configSummary = ref(null)

// Video generation
const videoFps = ref(24)
const videoCodec = ref('h264')
const videoQuality = ref('high')
const useMiddleBracket = ref(true)
const isGenerating = ref(false)

// UI state
const isConfiguring = ref(false)
const error = ref(null)
const showVideoOptions = ref(false)

const isRunning = computed(() => status.value.state === 'running')
const isPaused = computed(() => status.value.state === 'paused')
const isIdle = computed(() => ['idle', 'completed', 'cancelled', 'error'].includes(status.value.state))
const hasFrames = computed(() => status.value.frames_captured > 0)
const isBracketing = computed(() => status.value.bracketing?.enabled || status.value.multi_bracket_active)

const progressPercent = computed(() => {
  if (status.value.total_frames === 0) return 0
  if (isBracketing.value) {
    return Math.round((status.value.bracket_sets_captured / status.value.total_frames) * 100)
  }
  return Math.round((status.value.frames_captured / status.value.total_frames) * 100)
})

const computedTotalFrames = computed(() => {
  if (useFrameCount.value) {
    return totalFrames.value
  }
  return Math.floor((durationMinutes.value * 60) / intervalSeconds.value)
})

// shotsPerBracket is defined in the multi-bracket section below

const totalShots = computed(() => {
  return computedTotalFrames.value * shotsPerBracket.value
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

// Quick bracket type definitions
const bracketTypes = {
  exposure: {
    label: 'Exposure',
    icon: 'EV',
    setting: 'exposurecompensation',
    presets: ['-2', '-1', '0', '+1', '+2'],
    defaultValues: ['-2', '0', '+2']
  },
  iso: {
    label: 'ISO',
    icon: 'ISO',
    setting: 'iso',
    presets: ['100', '200', '400', '800', '1600', '3200', '6400'],
    defaultValues: ['100', '400', '1600']
  },
  aperture: {
    label: 'Aperture',
    icon: 'f/',
    setting: 'aperture',
    presets: ['1.4', '2', '2.8', '4', '5.6', '8', '11', '16', '22'],
    defaultValues: ['2.8', '5.6', '11']
  },
  shutter: {
    label: 'Shutter',
    icon: 'S',
    setting: 'shutterspeed',
    presets: ['1/4000', '1/2000', '1/1000', '1/500', '1/250', '1/125', '1/60', '1/30', '1/15'],
    defaultValues: ['1/250', '1/125', '1/60']
  }
}

// Check if any bracket type is enabled
const anyBracketTypeEnabled = computed(() => {
  return exposureEnabled.value || isoEnabled.value || apertureEnabled.value || shutterEnabled.value
})

// Generate steps preview for quick mode
const quickModeSteps = computed(() => {
  const steps = []

  if (combineMode.value === 'sequence') {
    // Concatenate all enabled types
    if (exposureEnabled.value) {
      exposureValues.value.forEach(val => {
        steps.push({ settings: { exposurecompensation: val }, label: `${val} EV` })
      })
    }
    if (isoEnabled.value) {
      isoValues.value.forEach(val => {
        steps.push({ settings: { iso: val }, label: `ISO ${val}` })
      })
    }
    if (apertureEnabled.value) {
      apertureValues.value.forEach(val => {
        steps.push({ settings: { aperture: val }, label: `f/${val}` })
      })
    }
    if (shutterEnabled.value) {
      shutterValues.value.forEach(val => {
        steps.push({ settings: { shutterspeed: val }, label: val })
      })
    }
  } else {
    // Paired mode: combine at same indices
    const enabledTypes = []
    if (exposureEnabled.value) enabledTypes.push({ setting: 'exposurecompensation', values: exposureValues.value, prefix: 'EV' })
    if (isoEnabled.value) enabledTypes.push({ setting: 'iso', values: isoValues.value, prefix: 'ISO ' })
    if (apertureEnabled.value) enabledTypes.push({ setting: 'aperture', values: apertureValues.value, prefix: 'f/' })
    if (shutterEnabled.value) enabledTypes.push({ setting: 'shutterspeed', values: shutterValues.value, prefix: '' })

    if (enabledTypes.length > 0) {
      const maxLen = Math.max(...enabledTypes.map(t => t.values.length))
      for (let i = 0; i < maxLen; i++) {
        const settings = {}
        const labels = []
        enabledTypes.forEach(({ setting, values, prefix }) => {
          if (i < values.length) {
            settings[setting] = values[i]
            labels.push(`${prefix}${values[i]}`)
          }
        })
        if (Object.keys(settings).length > 0) {
          steps.push({ settings, label: labels.join(' / ') })
        }
      }
    }
  }

  return steps
})

// Calculate shots per bracket based on mode
const shotsPerBracket = computed(() => {
  if (!bracketEnabled.value) return 1

  if (bracketMode.value === 'quick') {
    return quickModeSteps.value.length || 1
  } else {
    return advancedSteps.value.length || 1
  }
})

// Multi-bracket preset options
const multiBracketPresetOptions = computed(() => {
  return Object.entries(multiBracketPresets.value).map(([key, preset]) => ({
    value: key,
    label: key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    shots: preset.shots_per_bracket,
    types: preset.active_types?.join(', ') || ''
  }))
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

async function fetchBracketPresets() {
  try {
    const [legacyResponse, multiResponse] = await Promise.all([
      fetch('/api/timelapse/bracket-presets'),
      fetch('/api/timelapse/multi-bracket/presets')
    ])

    if (legacyResponse.ok) {
      bracketPresets.value = await legacyResponse.json()
    }
    if (multiResponse.ok) {
      multiBracketPresets.value = await multiResponse.json()
    }
  } catch (e) {
    console.error('Failed to fetch bracket presets:', e)
  }
}

async function estimateDiskSpace() {
  try {
    const response = await fetch('/api/timelapse/estimate-disk-space', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        total_frames: computedTotalFrames.value,
        format_type: 'raw',
        bracket_shots: shotsPerBracket.value
      })
    })
    if (response.ok) {
      diskEstimate.value = await response.json()
    }
  } catch (e) {
    console.error('Failed to estimate disk space:', e)
  }
}

async function configureBracket() {
  if (!bracketEnabled.value) {
    // Disable both legacy and multi-bracket
    await Promise.all([
      fetch('/api/timelapse/configure/bracket-disable', { method: 'POST' }),
      fetch('/api/timelapse/configure/multi-bracket/disable', { method: 'POST' })
    ])
    return
  }

  try {
    if (bracketMode.value === 'quick') {
      // Use quick setup API
      const response = await fetch('/api/timelapse/configure/multi-bracket/quick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          exposure_enabled: exposureEnabled.value,
          exposure_values: exposureValues.value,
          iso_enabled: isoEnabled.value,
          iso_values: isoValues.value,
          aperture_enabled: apertureEnabled.value,
          aperture_values: apertureValues.value,
          shutter_enabled: shutterEnabled.value,
          shutter_values: shutterValues.value,
          combine_mode: combineMode.value
        })
      })
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Multi-bracket configuration failed')
      }
      const result = await response.json()
      generatedSteps.value = result.generated_steps || []
    } else if (bracketMode.value === 'advanced') {
      if (selectedPreset.value) {
        // Use preset
        const response = await fetch('/api/timelapse/configure/multi-bracket/preset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preset_name: selectedPreset.value })
        })
        if (!response.ok) {
          const data = await response.json()
          throw new Error(data.detail || 'Preset configuration failed')
        }
      } else if (advancedSteps.value.length >= 2) {
        // Use custom steps
        const response = await fetch('/api/timelapse/configure/multi-bracket', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            enabled: true,
            active_types: getActiveTypesFromSteps(advancedSteps.value),
            steps: advancedSteps.value
          })
        })
        if (!response.ok) {
          const data = await response.json()
          throw new Error(data.detail || 'Advanced bracket configuration failed')
        }
      }
    }
  } catch (e) {
    error.value = e.message
  }
}

function getActiveTypesFromSteps(steps) {
  const types = new Set()
  steps.forEach(step => {
    if (step.settings) {
      if ('exposurecompensation' in step.settings) types.add('exposure')
      if ('iso' in step.settings) types.add('iso')
      if ('aperture' in step.settings) types.add('aperture')
      if ('shutterspeed' in step.settings) types.add('shutter')
    }
  })
  return Array.from(types)
}

function toggleValue(valuesRef, value) {
  const idx = valuesRef.value.indexOf(value)
  if (idx >= 0) {
    if (valuesRef.value.length > 1) {
      valuesRef.value.splice(idx, 1)
    }
  } else {
    valuesRef.value.push(value)
    // Sort appropriately based on type
    valuesRef.value.sort((a, b) => parseFloat(a) - parseFloat(b))
  }
}

function loadPresetToAdvanced(presetName) {
  const preset = multiBracketPresets.value[presetName]
  if (preset && preset.steps) {
    advancedSteps.value = preset.steps.map(s => ({
      settings: { ...s.settings },
      label: s.label || '',
      delay_ms: s.delay_ms || 0
    }))
    selectedPreset.value = presetName
    // Expand all loaded steps so users can see the settings
    expandedSteps.value = new Set(advancedSteps.value.map((_, i) => i))
  }
}

function addAdvancedStep() {
  const newIndex = advancedSteps.value.length
  advancedSteps.value.push({
    settings: {},
    label: `Step ${newIndex + 1}`,
    delay_ms: 0
  })
  expandedSteps.value.add(newIndex)  // Auto-expand new step
}

function toggleStepExpand(index) {
  if (expandedSteps.value.has(index)) {
    expandedSteps.value.delete(index)
  } else {
    expandedSteps.value.add(index)
  }
}

function toggleStepSetting(step, settingKey, enabled) {
  if (enabled) {
    // Add setting with default value
    const defaults = {
      exposurecompensation: '0',
      iso: '400',
      aperture: '5.6',
      shutterspeed: '1/125'
    }
    step.settings[settingKey] = defaults[settingKey]
  } else {
    delete step.settings[settingKey]
  }
}

function removeAdvancedStep(index) {
  if (advancedSteps.value.length > 2) {
    advancedSteps.value.splice(index, 1)
  }
}

async function configure() {
  isConfiguring.value = true
  error.value = null

  try {
    // Configure bracketing first
    await configureBracket()

    const payload = {
      interval_seconds: intervalSeconds.value,
    }

    if (useFrameCount.value) {
      payload.total_frames = totalFrames.value
    } else {
      payload.duration_seconds = durationMinutes.value * 60
    }

    // Include bracket config if enabled
    if (bracketEnabled.value && bracketPresets.value[bracketPreset.value]) {
      payload.bracket_config = bracketPresets.value[bracketPreset.value]
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
  configSummary.value = null  // Reset to force reconfigure

  await configure()
  if (error.value) return

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
        quality: videoQuality.value,
        use_middle_bracket: useMiddleBracket.value
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

// Update interval minimum when bracketing changes
watch(bracketEnabled, (enabled) => {
  if (enabled && intervalSeconds.value < 5) {
    intervalSeconds.value = 5
  }
})

// Auto-enable bracket when any type is toggled on
watch([exposureEnabled, isoEnabled, apertureEnabled, shutterEnabled], () => {
  if (anyBracketTypeEnabled.value && !bracketEnabled.value) {
    bracketEnabled.value = true
  }
})

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

watch(isPaused, (paused) => {
  if (paused && statusInterval) {
    clearInterval(statusInterval)
    statusInterval = null
  }
})

onMounted(() => {
  fetchStatus()
  fetchBracketPresets()
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
      <div class="flex items-center gap-2">
        <span
          v-if="isBracketing"
          class="text-xs px-2 py-0.5 rounded bg-camera-accent/20 text-camera-accent"
        >
          Bracket
        </span>
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
            :min="bracketEnabled ? 5 : 1"
            max="3600"
            class="w-full px-3 py-2 bg-camera-bg border border-camera-border rounded text-sm focus:outline-none focus:border-camera-accent"
          />
          <p class="text-xs text-camera-muted mt-1">
            {{ bracketEnabled ? 'Min 5s with bracketing' : 'Min 2s for RAW, 1s for JPEG' }}
          </p>
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
          <label class="block text-sm text-camera-muted mb-1">Total {{ bracketEnabled ? 'Bracket Sets' : 'Frames' }}</label>
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

        <!-- Bracketing Section -->
        <div class="border-t border-camera-border pt-4">
          <div class="flex items-center justify-between mb-3">
            <span class="text-sm font-medium">Bracketing</span>
            <button
              @click="bracketEnabled = !bracketEnabled"
              class="relative w-10 h-5 rounded-full transition-colors"
              :class="bracketEnabled ? 'bg-camera-accent' : 'bg-camera-border'"
            >
              <span
                class="absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform"
                :class="bracketEnabled ? 'left-5' : 'left-0.5'"
              ></span>
            </button>
          </div>

          <div v-if="bracketEnabled" class="space-y-3">
            <!-- Mode Toggle -->
            <div class="flex gap-1 bg-camera-bg p-1 rounded">
              <button
                @click="bracketMode = 'quick'"
                class="flex-1 px-2 py-1 text-xs rounded transition-colors"
                :class="bracketMode === 'quick' ? 'bg-camera-accent text-white' : 'text-camera-muted'"
              >
                Quick Setup
              </button>
              <button
                @click="bracketMode = 'advanced'"
                class="flex-1 px-2 py-1 text-xs rounded transition-colors"
                :class="bracketMode === 'advanced' ? 'bg-camera-accent text-white' : 'text-camera-muted'"
              >
                Advanced
              </button>
            </div>

            <!-- Quick Setup Mode -->
            <div v-if="bracketMode === 'quick'" class="space-y-3">
              <!-- Exposure Bracket -->
              <div class="p-2 bg-camera-bg rounded">
                <div class="flex items-center justify-between mb-2">
                  <label class="flex items-center gap-2">
                    <input type="checkbox" v-model="exposureEnabled" class="w-4 h-4 rounded" />
                    <span class="text-xs font-medium">Exposure (EV)</span>
                  </label>
                </div>
                <div v-if="exposureEnabled" class="flex flex-wrap gap-1">
                  <button
                    v-for="val in bracketTypes.exposure.presets"
                    :key="val"
                    @click="toggleValue(exposureValues, val)"
                    class="px-2 py-0.5 text-xs rounded transition-colors"
                    :class="exposureValues.includes(val) ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-muted'"
                  >
                    {{ val }}
                  </button>
                </div>
              </div>

              <!-- ISO Bracket -->
              <div class="p-2 bg-camera-bg rounded">
                <div class="flex items-center justify-between mb-2">
                  <label class="flex items-center gap-2">
                    <input type="checkbox" v-model="isoEnabled" class="w-4 h-4 rounded" />
                    <span class="text-xs font-medium">ISO</span>
                  </label>
                </div>
                <div v-if="isoEnabled" class="flex flex-wrap gap-1">
                  <button
                    v-for="val in bracketTypes.iso.presets"
                    :key="val"
                    @click="toggleValue(isoValues, val)"
                    class="px-2 py-0.5 text-xs rounded transition-colors"
                    :class="isoValues.includes(val) ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-muted'"
                  >
                    {{ val }}
                  </button>
                </div>
              </div>

              <!-- Aperture Bracket -->
              <div class="p-2 bg-camera-bg rounded">
                <div class="flex items-center justify-between mb-2">
                  <label class="flex items-center gap-2">
                    <input type="checkbox" v-model="apertureEnabled" class="w-4 h-4 rounded" />
                    <span class="text-xs font-medium">Aperture (f/)</span>
                  </label>
                </div>
                <div v-if="apertureEnabled" class="flex flex-wrap gap-1">
                  <button
                    v-for="val in bracketTypes.aperture.presets"
                    :key="val"
                    @click="toggleValue(apertureValues, val)"
                    class="px-2 py-0.5 text-xs rounded transition-colors"
                    :class="apertureValues.includes(val) ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-muted'"
                  >
                    f/{{ val }}
                  </button>
                </div>
              </div>

              <!-- Shutter Bracket -->
              <div class="p-2 bg-camera-bg rounded">
                <div class="flex items-center justify-between mb-2">
                  <label class="flex items-center gap-2">
                    <input type="checkbox" v-model="shutterEnabled" class="w-4 h-4 rounded" />
                    <span class="text-xs font-medium">Shutter Speed</span>
                  </label>
                </div>
                <div v-if="shutterEnabled" class="flex flex-wrap gap-1">
                  <button
                    v-for="val in bracketTypes.shutter.presets"
                    :key="val"
                    @click="toggleValue(shutterValues, val)"
                    class="px-2 py-0.5 text-xs rounded transition-colors"
                    :class="shutterValues.includes(val) ? 'bg-camera-accent text-white' : 'bg-camera-border text-camera-muted'"
                  >
                    {{ val }}
                  </button>
                </div>
              </div>

              <!-- Combine Mode (when multiple types enabled) -->
              <div v-if="[exposureEnabled, isoEnabled, apertureEnabled, shutterEnabled].filter(Boolean).length > 1" class="p-2 bg-camera-bg rounded">
                <label class="block text-xs text-camera-muted mb-2">Combine Mode</label>
                <div class="flex gap-2">
                  <label class="flex items-center gap-1 text-xs">
                    <input type="radio" v-model="combineMode" value="sequence" />
                    <span>Sequence</span>
                  </label>
                  <label class="flex items-center gap-1 text-xs">
                    <input type="radio" v-model="combineMode" value="paired" />
                    <span>Paired</span>
                  </label>
                </div>
                <p class="text-xs text-camera-muted mt-1">
                  {{ combineMode === 'sequence' ? 'Each type adds shots sequentially' : 'Types combined at same positions' }}
                </p>
              </div>

              <!-- Preview -->
              <div v-if="quickModeSteps.length > 0" class="p-2 bg-camera-bg rounded">
                <label class="block text-xs text-camera-muted mb-1">Shot Preview ({{ quickModeSteps.length }} shots)</label>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="(step, i) in quickModeSteps.slice(0, 8)"
                    :key="i"
                    class="px-1.5 py-0.5 text-xs bg-camera-border rounded"
                  >
                    {{ step.label }}
                  </span>
                  <span v-if="quickModeSteps.length > 8" class="px-1.5 py-0.5 text-xs text-camera-muted">
                    +{{ quickModeSteps.length - 8 }} more
                  </span>
                </div>
              </div>
            </div>

            <!-- Advanced Mode -->
            <div v-else class="space-y-3">
              <!-- Preset Selector -->
              <div>
                <label class="block text-xs text-camera-muted mb-1">Load Preset</label>
                <select
                  v-model="selectedPreset"
                  @change="loadPresetToAdvanced(selectedPreset)"
                  class="w-full px-2 py-1.5 bg-camera-bg border border-camera-border rounded text-xs"
                >
                  <option value="">Custom...</option>
                  <option v-for="opt in multiBracketPresetOptions" :key="opt.value" :value="opt.value">
                    {{ opt.label }} ({{ opt.shots }} shots)
                  </option>
                </select>
              </div>

              <!-- Shot List with Expandable Settings -->
              <div class="space-y-2 max-h-64 overflow-y-auto">
                <div
                  v-for="(step, i) in advancedSteps"
                  :key="i"
                  class="bg-camera-bg rounded overflow-hidden"
                >
                  <!-- Header row (always visible) -->
                  <div class="flex items-center gap-2 p-2">
                    <span class="w-5 text-camera-muted text-xs">#{{ i + 1 }}</span>
                    <input
                      v-model="step.label"
                      type="text"
                      placeholder="Label"
                      class="flex-1 px-2 py-1 bg-camera-surface border border-camera-border rounded text-xs"
                    />
                    <button
                      @click="toggleStepExpand(i)"
                      class="px-2 py-1 text-camera-muted hover:bg-camera-surface rounded text-xs"
                    >
                      {{ expandedSteps.has(i) ? '▲' : '▼' }}
                    </button>
                    <button
                      @click="removeAdvancedStep(i)"
                      :disabled="advancedSteps.length <= 2"
                      class="px-2 py-1 text-camera-error hover:bg-camera-error/10 rounded disabled:opacity-30"
                    >
                      ×
                    </button>
                  </div>

                  <!-- Settings section (expandable) -->
                  <div v-if="expandedSteps.has(i)" class="px-2 pb-2 space-y-2 border-t border-camera-border/50">
                    <!-- Exposure setting -->
                    <div class="flex items-center gap-2 pt-2">
                      <input
                        type="checkbox"
                        :checked="'exposurecompensation' in step.settings"
                        @change="toggleStepSetting(step, 'exposurecompensation', $event.target.checked)"
                        class="w-3 h-3"
                      />
                      <span class="text-xs w-16">Exposure</span>
                      <select
                        v-if="'exposurecompensation' in step.settings"
                        v-model="step.settings.exposurecompensation"
                        class="flex-1 px-2 py-1 bg-camera-surface border border-camera-border rounded text-xs"
                      >
                        <option v-for="val in bracketTypes.exposure.presets" :key="val" :value="val">{{ val }} EV</option>
                      </select>
                      <span v-else class="flex-1 text-xs text-camera-muted">--</span>
                    </div>
                    <!-- ISO setting -->
                    <div class="flex items-center gap-2">
                      <input
                        type="checkbox"
                        :checked="'iso' in step.settings"
                        @change="toggleStepSetting(step, 'iso', $event.target.checked)"
                        class="w-3 h-3"
                      />
                      <span class="text-xs w-16">ISO</span>
                      <select
                        v-if="'iso' in step.settings"
                        v-model="step.settings.iso"
                        class="flex-1 px-2 py-1 bg-camera-surface border border-camera-border rounded text-xs"
                      >
                        <option v-for="val in bracketTypes.iso.presets" :key="val" :value="val">{{ val }}</option>
                      </select>
                      <span v-else class="flex-1 text-xs text-camera-muted">--</span>
                    </div>
                    <!-- Aperture setting -->
                    <div class="flex items-center gap-2">
                      <input
                        type="checkbox"
                        :checked="'aperture' in step.settings"
                        @change="toggleStepSetting(step, 'aperture', $event.target.checked)"
                        class="w-3 h-3"
                      />
                      <span class="text-xs w-16">Aperture</span>
                      <select
                        v-if="'aperture' in step.settings"
                        v-model="step.settings.aperture"
                        class="flex-1 px-2 py-1 bg-camera-surface border border-camera-border rounded text-xs"
                      >
                        <option v-for="val in bracketTypes.aperture.presets" :key="val" :value="val">f/{{ val }}</option>
                      </select>
                      <span v-else class="flex-1 text-xs text-camera-muted">--</span>
                    </div>
                    <!-- Shutter setting -->
                    <div class="flex items-center gap-2">
                      <input
                        type="checkbox"
                        :checked="'shutterspeed' in step.settings"
                        @change="toggleStepSetting(step, 'shutterspeed', $event.target.checked)"
                        class="w-3 h-3"
                      />
                      <span class="text-xs w-16">Shutter</span>
                      <select
                        v-if="'shutterspeed' in step.settings"
                        v-model="step.settings.shutterspeed"
                        class="flex-1 px-2 py-1 bg-camera-surface border border-camera-border rounded text-xs"
                      >
                        <option v-for="val in bracketTypes.shutter.presets" :key="val" :value="val">{{ val }}</option>
                      </select>
                      <span v-else class="flex-1 text-xs text-camera-muted">--</span>
                    </div>
                  </div>
                </div>
              </div>

              <button
                @click="addAdvancedStep"
                :disabled="advancedSteps.length >= 15"
                class="w-full py-1.5 text-xs bg-camera-border text-camera-text rounded hover:bg-camera-border/80 disabled:opacity-50"
              >
                + Add Shot
              </button>
            </div>

            <!-- Bracket Info -->
            <div class="p-2 bg-camera-accent/10 rounded text-xs">
              <div class="flex justify-between">
                <span class="text-camera-muted">Shots per interval:</span>
                <span class="font-medium">{{ shotsPerBracket }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-camera-muted">Total shots:</span>
                <span class="font-medium">{{ totalShots }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Summary -->
        <div class="p-3 bg-camera-bg rounded text-sm space-y-1">
          <div class="flex justify-between">
            <span class="text-camera-muted">{{ bracketEnabled ? 'Bracket Sets:' : 'Frames:' }}</span>
            <span>{{ computedTotalFrames }}</span>
          </div>
          <div v-if="bracketEnabled" class="flex justify-between">
            <span class="text-camera-muted">Total Shots:</span>
            <span>{{ totalShots }}</span>
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
          {{ isConfiguring ? 'Configuring...' : (bracketEnabled ? 'Start Bracketed Time-lapse' : 'Start Time-lapse') }}
        </button>
      </div>

      <!-- Progress (when running/paused) -->
      <div v-else class="space-y-4">
        <!-- Progress Bar -->
        <div>
          <div class="flex justify-between text-sm mb-1">
            <span v-if="isBracketing">
              {{ status.bracket_sets_captured }} / {{ status.total_frames }} sets
              ({{ status.frames_captured }} shots)
            </span>
            <span v-else>
              {{ status.frames_captured }} / {{ status.total_frames }} frames
            </span>
            <span>{{ progressPercent }}%</span>
          </div>
          <div class="w-full h-3 bg-camera-border rounded-full overflow-hidden">
            <div
              class="h-full bg-camera-accent transition-all duration-300"
              :style="{ width: `${progressPercent}%` }"
            ></div>
          </div>
        </div>

        <!-- Bracket Info (if bracketing) -->
        <div v-if="isBracketing" class="p-2 bg-camera-accent/10 rounded text-xs">
          <span class="text-camera-accent font-medium">
            {{ status.multi_bracket_active ? 'Multi-Bracket' : (status.bracketing?.bracket_type?.toUpperCase() || 'Bracket') }}
          </span>
          <span class="text-camera-muted ml-2">
            {{ status.bracketing?.shots_per_bracket || shotsPerBracket }} shots per set
          </span>
          <div v-if="status.bracketing?.active_types?.length > 1" class="mt-1 text-camera-muted">
            Types: {{ status.bracketing.active_types.join(', ') }}
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

          <!-- Bracket video option -->
          <div v-if="status.bracketing?.enabled" class="flex items-center gap-2">
            <input
              type="checkbox"
              id="useMiddleBracket"
              v-model="useMiddleBracket"
              class="w-4 h-4"
            />
            <label for="useMiddleBracket" class="text-xs text-camera-muted">
              Use middle exposure from each bracket set
            </label>
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
