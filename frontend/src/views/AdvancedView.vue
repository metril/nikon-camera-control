<script setup>
import FocusCard from '@/components/advanced/FocusCard.vue'
import FocusStackCard from '@/components/advanced/FocusStackCard.vue'
import BulbCard from '@/components/advanced/BulbCard.vue'
import BracketCard from '@/components/advanced/BracketCard.vue'
import RecordingCard from '@/components/advanced/RecordingCard.vue'
import PresetsCard from '@/components/advanced/PresetsCard.vue'
import CameraAdminCard from '@/components/advanced/CameraAdminCard.vue'

// 'gallery' / 'timelapse' (+ optional folder): the shell decides how to switch tabs.
const emit = defineEmits(['navigate'])
const nav = (...args) => emit('navigate', ...args)
</script>

<template>
  <div class="grid grid-cols-1 items-start gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
    <FocusCard />
    <FocusStackCard @navigate="nav" />
    <BulbCard />
    <BracketCard @navigate="nav" />
    <RecordingCard />
    <PresetsCard @navigate="nav" />
    <CameraAdminCard />
  </div>
</template>
