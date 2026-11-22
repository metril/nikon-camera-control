<script setup>
defineProps({ title: { type: String, default: '' }, subtitle: { type: String, default: '' } })
</script>

<template>
  <section class="rounded-lg border border-camera-border bg-camera-surface">
    <header
      v-if="title || subtitle || $slots.actions"
      class="flex flex-wrap items-start justify-between gap-2 border-b border-camera-border px-4 py-3"
    >
      <div class="min-w-0">
        <h2 v-if="title" class="text-sm font-semibold">{{ title }}</h2>
        <p v-if="subtitle" class="text-xs text-camera-muted">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="flex items-center gap-2"><slot name="actions" /></div>
    </header>
    <div class="p-4"><slot /></div>
  </section>
</template>
