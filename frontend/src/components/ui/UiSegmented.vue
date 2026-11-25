<script setup>
const props = defineProps({
  modelValue: { type: [String, Number, Boolean, Array], default: null },
  options: { type: Array, default: () => [] },
  multiple: Boolean,
  disabled: Boolean,
  /** sm | md */
  size: { type: String, default: 'md' },
})
const emit = defineEmits(['update:modelValue'])

const isOn = (v) => (props.multiple ? (props.modelValue || []).includes(v) : props.modelValue === v)
function pick(v) {
  if (!props.multiple) return emit('update:modelValue', v)
  const cur = props.modelValue || []
  emit('update:modelValue', cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v])
}
</script>

<template>
  <div
    role="group"
    class="seg inline-flex max-w-full gap-0.5 rounded-control border border-camera-border bg-camera-bg"
    :class="size === 'sm' ? 'seg-sm h-[var(--ctl-sm)] p-0.5' : 'h-[var(--ctl)] p-[3px]'"
    style="overflow-x: auto"
  >
    <button
      v-for="o in options"
      :key="String(o.value)"
      type="button"
      :aria-pressed="isOn(o.value)"
      :disabled="disabled"
      class="inline-flex flex-auto items-center justify-center gap-1.5 whitespace-nowrap rounded-[4px] px-3 text-[13px] font-medium transition-colors duration-[120ms] disabled:cursor-not-allowed disabled:opacity-[.45]"
      :class="
        isOn(o.value)
          ? 'bg-camera-accent/15 text-camera-text shadow-[inset_0_-2px_0_0_theme(colors.camera.accent)]'
          : 'text-camera-muted hover:text-camera-text active:bg-camera-subtle'
      "
      @click="pick(o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>

<style scoped>
/* Touch: the buttons themselves must be 44px tall, so the small group grows by its padding and border */
html[data-layout='touch'] .seg-sm {
  height: calc(var(--ctl-sm) + 6px);
}
</style>
