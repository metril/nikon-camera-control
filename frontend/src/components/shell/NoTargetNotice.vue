<script setup>
import { inject } from 'vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiButton from '@/components/ui/UiButton.vue'
defineProps({ compact: Boolean })
const navigate = inject('navigate', null)
const openSettings = () => {
  if (navigate) navigate('settings', { section: 'storage' })
  else window.location.hash = '#/settings?section=storage'
}
</script>

<template>
  <div
    v-if="compact"
    class="flex flex-wrap items-center gap-2 text-sm text-camera-warn"
    role="status"
    data-test="no-target"
  >
    <span>No storage chosen. Choose one in Settings › Storage.</span>
    <UiButton size="sm" data-test="open-storage" @click="openSettings">Open settings</UiButton>
  </div>
  <UiEmpty
    v-else
    title="No storage chosen"
    hint="Choose one in Settings › Storage."
    data-test="no-target"
  >
    <template #actions>
      <UiButton variant="primary" size="sm" data-test="open-storage" @click="openSettings">
        Open settings
      </UiButton>
    </template>
  </UiEmpty>
</template>
