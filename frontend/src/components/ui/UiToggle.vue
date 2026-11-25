<script setup>
defineProps({
  modelValue: Boolean,
  label: { type: String, default: '' },
  disabled: Boolean,
})
defineEmits(['update:modelValue'])
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    class="inline-flex min-h-[var(--ctl-sm)] items-center gap-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 [html[data-layout='touch']_&]:min-w-[44px]"
    :class="{ 'justify-center': !label }"
    @click="$emit('update:modelValue', !modelValue)"
  >
    <span
      class="relative h-5 w-9 shrink-0 rounded-full transition-colors motion-reduce:transition-none"
      :class="modelValue ? 'bg-camera-accent' : 'bg-camera-border'"
    >
      <span
        class="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all motion-reduce:transition-none"
        :class="modelValue ? 'left-[1.125rem]' : 'left-0.5'"
      />
    </span>
    <span v-if="label">{{ label }}</span>
  </button>
</template>
