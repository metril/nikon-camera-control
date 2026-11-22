<script setup>
const props = defineProps({
  modelValue: { type: [String, Number, Boolean, Array], default: null },
  options: { type: Array, default: () => [] },
  multiple: Boolean,
  disabled: Boolean,
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
  <div role="group" class="inline-flex flex-wrap gap-1 rounded-md bg-camera-bg p-1">
    <button
      v-for="o in options"
      :key="String(o.value)"
      type="button"
      :aria-pressed="isOn(o.value)"
      :disabled="disabled"
      class="rounded px-3 py-1 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50"
      :class="
        isOn(o.value)
          ? 'bg-camera-accent font-medium text-black'
          : 'text-camera-text hover:bg-camera-border'
      "
      @click="pick(o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>
