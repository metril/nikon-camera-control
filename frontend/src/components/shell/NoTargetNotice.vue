<script setup>
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiButton from '@/components/ui/UiButton.vue'
defineProps({ compact: Boolean })
const emit = defineEmits(['open-settings'])
const openSettings = () => {
  emit('open-settings')
  window.location.hash = '#/settings'
}
</script>

<template>
  <div
    v-if="compact"
    class="flex flex-wrap items-center gap-2 text-sm text-camera-warn"
    role="status"
    data-test="no-target"
  >
    <span>No storage target. Choose one in Settings › Storage.</span>
    <a href="#/settings" class="underline" @click="emit('open-settings')">Open settings</a>
  </div>
  <UiEmpty
    v-else
    title="No storage target"
    hint="Choose one in Settings › Storage."
    data-test="no-target"
  >
    <template #actions>
      <UiButton variant="primary" size="sm" @click="openSettings">Open settings</UiButton>
    </template>
  </UiEmpty>
</template>
