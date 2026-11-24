<script setup>
/** tone: neutral | ok | warn | danger | accent (error and info are aliases: danger / neutral) */
defineProps({ tone: { type: String, default: 'neutral' } })
const TONES = {
  neutral: 'border-camera-border text-camera-muted',
  info: 'border-camera-border text-camera-muted',
  ok: 'border-camera-ok/30 text-camera-ok',
  warn: 'border-camera-warn/30 text-camera-warn',
  danger: 'border-camera-danger/30 text-camera-danger',
  error: 'border-camera-danger/30 text-camera-danger',
  accent: 'border-camera-accent/40 text-camera-accent',
}
</script>

<template>
  <span
    class="inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-xs font-medium"
    :class="TONES[tone] || TONES.neutral"
  >
    <slot />
  </span>
</template>
