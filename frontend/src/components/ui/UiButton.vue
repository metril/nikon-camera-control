<script setup>
import { computed } from 'vue'
import UiSpinner from './UiSpinner.vue'

const props = defineProps({
  variant: { type: String, default: 'secondary' },
  size: { type: String, default: 'md' },
  loading: Boolean,
  disabled: Boolean,
  type: { type: String, default: 'button' },
})

const VARIANTS = {
  primary: 'bg-camera-accent text-black hover:brightness-110 border-transparent font-medium',
  secondary: 'bg-camera-border text-camera-text hover:bg-neutral-600 border-transparent',
  danger: 'bg-camera-error text-white hover:brightness-110 border-transparent',
  ghost: 'bg-transparent text-camera-text hover:bg-camera-border border-camera-border',
}
const cls = computed(() => [
  VARIANTS[props.variant] || VARIANTS.secondary,
  props.size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-4 py-2 text-sm',
])
</script>

<template>
  <button
    :type="type"
    :disabled="disabled || loading"
    :aria-busy="loading || undefined"
    class="inline-flex items-center justify-center gap-2 rounded-md border transition-colors disabled:cursor-not-allowed disabled:opacity-50"
    :class="cls"
  >
    <UiSpinner v-if="loading" size="sm" />
    <slot />
  </button>
</template>
