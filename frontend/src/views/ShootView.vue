<script setup>
import ModeWarning from '@/components/shoot/ModeWarning.vue'
import LiveViewPanel from '@/components/shoot/LiveViewPanel.vue'
import CaptureControls from '@/components/shoot/CaptureControls.vue'
import SettingsPanel from '@/components/shoot/SettingsPanel.vue'

// Emitted so the shell can switch to the Gallery view.
const emit = defineEmits(['open-gallery'])
</script>

<template>
  <div class="flex flex-col gap-4">
    <ModeWarning />
    <div class="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div class="flex min-w-0 flex-col gap-4">
        <LiveViewPanel />
        <CaptureControls @open-gallery="emit('open-gallery')" />
      </div>
      <SettingsPanel class="min-w-0" />
    </div>
  </div>
</template>
