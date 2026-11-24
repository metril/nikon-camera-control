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
    class="inline-flex max-w-full gap-0.5 rounded-control border border-camera-border bg-camera-bg"
    :class="size === 'sm' ? 'h-[var(--ctl-sm)] p-0.5' : 'h-[var(--ctl)] p-[3px]'"
  >
    <button
      v-for="o in options"
      :key="String(o.value)"
      type="button"
      :aria-pressed="isOn(o.value)"
      :disabled="disabled"
      class="inline-flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-[4px] px-3 text-[13px] font-medium transition-colors duration-[120ms] disabled:cursor-not-allowed disabled:opacity-[.45]"
      :class="
        isOn(o.value)
          ? 'bg-camera-raised text-camera-text shadow-[inset_0_0_0_1px_#3a3a3a]'
          : 'text-camera-muted hover:text-camera-text active:bg-camera-subtle'
      "
      @click="pick(o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>
