<script setup>
import { computed } from 'vue'
import UiSpinner from './UiSpinner.vue'

const props = defineProps({
  /** primary | secondary | ghost | danger | shutter | danger-quiet */
  variant: { type: String, default: 'secondary' },
  /** sm | md (ignored for shutter) */
  size: { type: String, default: 'md' },
  loading: Boolean,
  disabled: Boolean,
  /** shutter only: show the stop (square) state */
  stop: Boolean,
  type: { type: String, default: 'button' },
})

const VARIANTS = {
  primary:
    'bg-camera-accent border-camera-accent text-camera-accent-ink font-medium hover:bg-camera-accent-hover active:bg-camera-accent-press',
  secondary:
    'bg-camera-raised border-camera-border text-camera-text font-medium hover:bg-camera-hover active:bg-camera-border',
  ghost:
    'bg-transparent border-transparent text-camera-muted hover:text-camera-text hover:bg-camera-raised active:bg-camera-hover',
  danger:
    'bg-camera-danger-fill border-camera-danger-fill text-white font-medium hover:brightness-110 active:brightness-90',
  'danger-quiet':
    'bg-transparent border-camera-danger text-camera-danger font-medium hover:bg-camera-raised active:bg-camera-hover',
}
const isShutter = computed(() => props.variant === 'shutter')
const cls = computed(() => [
  VARIANTS[props.variant] || VARIANTS.secondary,
  props.size === 'sm' ? 'h-[var(--ctl-sm)] px-2.5 text-[13px]' : 'h-[var(--ctl)] px-3.5 text-sm',
])
</script>

<template>
  <button
    v-if="isShutter"
    :type="type"
    :disabled="loading"
    :aria-disabled="disabled || loading || undefined"
    :aria-busy="loading || undefined"
    class="shutter"
    :class="{ stop }"
  >
    <span class="shutter-core"></span>
  </button>
  <button
    v-else
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    class="inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control border transition-colors duration-[120ms] disabled:cursor-not-allowed disabled:opacity-[.45]"
    :class="cls"
  >
    <UiSpinner v-if="loading" size="sm" />
    <slot />
  </button>
</template>

<style scoped>
.shutter {
  width: 84px;
  height: 84px;
  min-height: 0;
  flex: none;
  border-radius: 9999px;
  border: 3px solid theme('colors.camera.text');
  background: none;
  padding: 5px;
  cursor: pointer;
}
html[data-layout='touch'] .shutter {
  width: 72px;
  height: 72px;
}
.shutter-core {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 9999px;
  background: theme('colors.camera.accent');
  transition:
    transform 80ms,
    background-color 120ms,
    border-radius 120ms;
}
.shutter:hover:not(:disabled, [aria-disabled='true']) .shutter-core {
  background: theme('colors.camera.accent-hover');
}
.shutter:active:not(:disabled, [aria-disabled='true']) .shutter-core {
  transform: scale(0.9);
}
.shutter:disabled,
.shutter[aria-disabled='true'] {
  border-color: theme('colors.camera.border');
  cursor: not-allowed;
}
.shutter:disabled .shutter-core,
.shutter[aria-disabled='true'] .shutter-core {
  background: theme('colors.camera.border');
}
.shutter.stop {
  border-color: theme('colors.camera.danger');
}
.shutter.stop .shutter-core {
  background: theme('colors.camera.danger-fill');
  border-radius: 10px;
  transform: scale(0.55);
}
.shutter.stop:active:not(:disabled, [aria-disabled='true']) .shutter-core {
  transform: scale(0.5);
}
</style>
