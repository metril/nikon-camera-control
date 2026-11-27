<script setup>
import { computed } from 'vue'
import { useLayoutMode } from '@/composables/useLayoutMode'

const props = defineProps({
  modelValue: Boolean,
  /** Accessible name, e.g. "Select IMG_0001.jpg". */
  label: { type: String, default: '' },
  /** 'touch' = 28px, 'desktop' = 20px. Defaults to the current layout. */
  size: { type: String, default: '', validator: (v) => ['', 'touch', 'desktop'].includes(v) },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])

const { isTouch } = useLayoutMode()
const px = computed(() => {
  const touch = props.size ? props.size === 'touch' : isTouch.value
  return touch ? 28 : 20
})
</script>

<template>
  <button
    type="button"
    role="checkbox"
    :aria-checked="modelValue"
    :aria-label="label || undefined"
    :disabled="disabled"
    class="ui-check inline-flex shrink-0 items-center justify-center rounded-full border-2 transition-colors disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
    :class="
      modelValue
        ? 'border-camera-accent bg-camera-accent text-camera-accent-ink'
        : 'border-white/70 bg-black/40 text-transparent hover:border-white'
    "
    :style="{ width: `${px}px`, height: `${px}px`, minHeight: 0 }"
    :data-size="px"
    @click="emit('update:modelValue', !modelValue)"
  >
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      :style="{ width: `${Math.round(px * 0.6)}px`, height: `${Math.round(px * 0.6)}px` }"
    >
      <path d="M3 8.5l3.2 3L13 4.5" />
    </svg>
  </button>
</template>
