<script setup>
import { ref, computed } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import UiButton from '@/components/ui/UiButton.vue'

const camera = useCameraStore()
const settings = useSettingsStore()
const dismissed = ref(false)

const MODES = [
  { key: 'P', label: 'Program' },
  { key: 'A', label: 'Aperture' },
  { key: 'S', label: 'Shutter' },
  { key: 'M', label: 'Manual' },
]
const OK = /^(p|a|s|m)$|program|aperture|shutter|manual/i

const mode = computed(() => {
  const v = settings.get('expprogram') ?? settings.get('autoexposuremode')
  return v === null || v === undefined || v === '' ? null : String(v)
})
// Hide only when we know the dial is in a usable mode; unknown still shows the reminder.
const show = computed(
  () => camera.connected && !dismissed.value && !(mode.value && OK.test(mode.value)),
)
</script>

<template>
  <div
    v-if="show"
    class="rounded-lg border border-camera-warning/30 bg-camera-warning/10 px-4 py-3"
    role="status"
    aria-live="polite"
    data-testid="mode-warning"
  >
    <div class="flex items-start gap-3">
      <div class="flex-1">
        <h3 class="font-medium text-camera-warning">Mode Dial Requirement</h3>
        <p class="mt-1 text-sm text-camera-text/80">
          Ensure your camera's mode dial is set to <strong>P</strong>, <strong>A</strong>,
          <strong>S</strong>, or <strong>M</strong> mode. Auto and Scene modes will cause settings
          changes to silently fail.
          <span v-if="mode" data-testid="current-mode">Current mode: {{ mode }}.</span>
        </p>
        <ul class="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-xs">
          <li v-for="m in MODES" :key="m.key" class="flex items-center gap-1.5">
            <span
              class="flex h-6 w-6 items-center justify-center rounded bg-camera-success/20 font-bold text-camera-success"
              >{{ m.key }}</span
            >
            <span class="text-camera-muted">{{ m.label }}</span>
          </li>
        </ul>
      </div>
      <UiButton
        size="sm"
        variant="ghost"
        aria-label="Dismiss mode warning"
        @click="dismissed = true"
        >&times;</UiButton
      >
    </div>
  </div>
</template>
