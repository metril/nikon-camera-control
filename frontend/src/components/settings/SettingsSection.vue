<script setup>
defineProps({ title: { type: String, required: true }, subtitle: { type: String, default: '' } })
</script>

<template>
  <section class="rounded-card border border-camera-border bg-camera-surface p-4">
    <h2 class="text-sm font-semibold">{{ title }}</h2>
    <p v-if="subtitle" class="mt-0.5 text-[12.5px] text-camera-muted">{{ subtitle }}</p>
    <div class="mt-4"><slot /></div>
  </section>
</template>
