<script setup>
defineProps({ title: { type: String, default: '' }, hint: { type: String, default: '' } })
</script>

<template>
  <div class="flex flex-col items-center gap-2 px-4 py-10 text-center">
    <p v-if="title" class="font-medium">{{ title }}</p>
    <p v-if="hint" class="max-w-sm text-sm text-camera-muted">{{ hint }}</p>
    <div v-if="$slots.actions" class="mt-2 flex flex-wrap justify-center gap-2">
      <slot name="actions" />
    </div>
  </div>
</template>
