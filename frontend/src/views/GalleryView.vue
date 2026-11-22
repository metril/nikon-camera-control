<script setup>
import { ref } from 'vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import LocalFiles from '@/components/gallery/LocalFiles.vue'
import CameraFiles from '@/components/gallery/CameraFiles.vue'
import Videos from '@/components/gallery/Videos.vue'

const TABS = [
  { value: 'local', label: 'On this server' },
  { value: 'camera', label: 'On the camera card' },
  { value: 'videos', label: 'Videos' },
]
const tab = ref('local')
</script>

<template>
  <section class="space-y-4">
    <UiSegmented v-model="tab" :options="TABS" aria-label="Gallery source" />
    <LocalFiles v-if="tab === 'local'" />
    <CameraFiles v-else-if="tab === 'camera'" />
    <Videos v-else />
  </section>
</template>
