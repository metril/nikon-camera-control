<script setup>
/** Warns only when the camera reports a mode other than P, A, S or M (Auto, Scene, …). */
import { computed, ref } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import UiAlert from '@/components/ui/UiAlert.vue'
import { MODE_NAMES, SETTING_FOR, modeLetter } from './exposure'

const KEY = 'nikon-mode-warning-dismissed'
const camera = useCameraStore()
const settings = useSettingsStore()

const read = () => {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}
const dismissed = ref(read())
function dismiss() {
  dismissed.value = true
  try {
    localStorage.setItem(KEY, '1')
  } catch {
    /* storage unavailable */
  }
}

const mode = computed(() => {
  for (const n of SETTING_FOR.mode) {
    const v = settings.get(n)
    if (v !== null && v !== undefined && v !== '') return String(v)
  }
  return null
})
// Only a known, unusable mode warns: an unknown mode is not worth interrupting for.
const show = computed(
  () => camera.connected && !dismissed.value && !!mode.value && !modeLetter(mode.value),
)
const modes = Object.entries(MODE_NAMES).map(([k, v]) => `${k} (${v.toLowerCase()})`)
</script>

<template>
  <UiAlert
    v-if="show"
    tone="warn"
    title="Set the mode dial to P, A, S or M"
    dismissible
    data-testid="mode-warning"
    @dismiss="dismiss"
  >
    The camera is in <span data-testid="current-mode">{{ mode }}</span> mode. In Auto and Scene
    modes, setting changes silently fail. Use {{ modes.join(', ') }}.
  </UiAlert>
</template>
