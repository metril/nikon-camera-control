<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useCameraStore } from '../stores/camera'

const camera = useCameraStore()

// Local state for pending changes
const pendingValue = ref(null)
const activeSetting = ref(null)
const isUpdating = ref(false)

// Common settings to display
const settingGroups = [
  {
    title: 'Exposure',
    settings: [
      { key: 'iso', label: 'ISO', icon: 'ISO' },
      { key: 'aperture', label: 'Aperture', icon: 'f/' },
      { key: 'shutterspeed', label: 'Shutter', icon: 'S' },
    ]
  },
  {
    title: 'Focus & Metering',
    settings: [
      { key: 'focusmode', label: 'Focus Mode', icon: 'AF' },
      { key: 'meteringmode', label: 'Metering', icon: 'M' },
    ]
  },
  {
    title: 'Color & Format',
    settings: [
      { key: 'whitebalance', label: 'White Balance', icon: 'WB' },
      { key: 'imageformat', label: 'Format', icon: 'F' },
    ]
  }
]

function getSettingValue(key) {
  const setting = camera.settings[key]
  return setting?.current || '--'
}

function getSettingChoices(key) {
  const setting = camera.settings[key]
  return setting?.choices || []
}

function isSettingReadOnly(key) {
  const setting = camera.settings[key]
  return setting?.readonly || false
}

async function selectValue(settingKey, value) {
  if (isUpdating.value) return

  isUpdating.value = true
  activeSetting.value = settingKey

  try {
    await camera.setSetting(settingKey, value)
  } catch (error) {
    console.error(`Failed to set ${settingKey}:`, error)
  } finally {
    isUpdating.value = false
    activeSetting.value = null
  }
}

function formatValue(key, value) {
  if (!value || value === '--') return value

  // Format display values nicely
  switch (key) {
    case 'aperture':
      return value.startsWith('f/') ? value : `f/${value}`
    case 'shutterspeed':
      return value
    case 'iso':
      return value
    default:
      return value
  }
}

// Refresh settings on mount
onMounted(() => {
  if (camera.connected) {
    camera.fetchSettings()
  }
})

// Watch for connection changes
watch(() => camera.connected, (connected) => {
  if (connected) {
    camera.fetchSettings()
  }
})
</script>

<template>
  <div class="bg-camera-surface border border-camera-border rounded-lg overflow-hidden">
    <div class="px-4 py-2 border-b border-camera-border flex items-center justify-between">
      <h2 class="font-medium">Camera Settings</h2>
      <button
        v-if="camera.connected"
        @click="camera.fetchSettings"
        class="text-xs text-camera-muted hover:text-camera-text transition-colors"
        :disabled="isUpdating"
      >
        Refresh
      </button>
    </div>

    <div v-if="!camera.connected" class="p-4 text-center text-camera-muted">
      <p>Connect camera to view settings</p>
    </div>

    <div v-else class="p-4 space-y-6">
      <!-- Setting Groups -->
      <div v-for="group in settingGroups" :key="group.title">
        <h3 class="text-xs uppercase tracking-wider text-camera-muted mb-3">
          {{ group.title }}
        </h3>

        <div class="space-y-4">
          <div v-for="setting in group.settings" :key="setting.key" class="space-y-2">
            <!-- Setting Label and Current Value -->
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="w-8 h-8 flex items-center justify-center bg-camera-border rounded text-xs font-mono">
                  {{ setting.icon }}
                </span>
                <span class="text-sm">{{ setting.label }}</span>
              </div>
              <span class="text-sm font-medium text-camera-accent">
                {{ formatValue(setting.key, getSettingValue(setting.key)) }}
              </span>
            </div>

            <!-- Setting Choices -->
            <div
              v-if="getSettingChoices(setting.key).length > 0"
              class="flex flex-wrap gap-1.5"
            >
              <button
                v-for="choice in getSettingChoices(setting.key)"
                :key="choice"
                @click="selectValue(setting.key, choice)"
                :disabled="isSettingReadOnly(setting.key) || (isUpdating && activeSetting === setting.key)"
                class="px-2 py-1 text-xs rounded transition-colors"
                :class="[
                  getSettingValue(setting.key) === choice
                    ? 'bg-camera-accent text-white'
                    : 'bg-camera-border text-camera-text hover:bg-camera-border/80',
                  isSettingReadOnly(setting.key) ? 'opacity-50 cursor-not-allowed' : '',
                  isUpdating && activeSetting === setting.key ? 'opacity-50' : ''
                ]"
              >
                {{ formatValue(setting.key, choice) }}
              </button>
            </div>

            <!-- No choices available -->
            <div
              v-else
              class="text-xs text-camera-muted italic"
            >
              {{ isSettingReadOnly(setting.key) ? 'Read-only in current mode' : 'No options available' }}
            </div>
          </div>
        </div>
      </div>

      <!-- Battery Level -->
      <div v-if="camera.batteryLevel !== null" class="pt-4 border-t border-camera-border">
        <div class="flex items-center justify-between">
          <span class="text-sm text-camera-muted">Battery</span>
          <div class="flex items-center gap-2">
            <div class="w-20 h-2 bg-camera-border rounded-full overflow-hidden">
              <div
                class="h-full transition-all duration-300"
                :class="camera.batteryLevel > 20 ? 'bg-camera-success' : 'bg-camera-error'"
                :style="{ width: `${camera.batteryLevel}%` }"
              ></div>
            </div>
            <span class="text-xs font-medium">{{ camera.batteryLevel }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
