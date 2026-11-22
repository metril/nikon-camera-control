<script setup>
defineProps({ tone: { type: String, default: 'neutral' } })
const TONES = {
  neutral: 'bg-camera-border text-camera-text',
  ok: 'bg-green-500/15 text-green-400',
  warn: 'bg-yellow-500/15 text-yellow-400',
  error: 'bg-red-500/15 text-red-400',
  info: 'bg-sky-500/15 text-sky-400',
}
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
    :class="TONES[tone] || TONES.neutral"
  >
    <slot />
  </span>
</template>
