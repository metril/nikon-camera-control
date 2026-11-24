<script setup>
import { uid } from './uid'

defineProps({
  modelValue: { type: String, default: '' },
  label: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: Boolean,
  maxlength: { type: Number, default: undefined },
  /** Additive: input type (e.g. 'password'). */
  type: { type: String, default: 'text' },
})
defineEmits(['update:modelValue'])
const id = uid('text')
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <label v-if="label" :for="id" class="text-xs font-medium text-camera-muted">{{ label }}</label>
    <input
      :id="id"
      :type="type"
      :value="modelValue ?? ''"
      :placeholder="placeholder"
      :disabled="disabled"
      :maxlength="maxlength"
      class="h-[var(--ctl)] w-full min-w-0 rounded-control border border-camera-border bg-camera-bg px-3 text-sm text-camera-text placeholder:text-camera-faint hover:border-[#4a4a4a] disabled:cursor-not-allowed disabled:opacity-[.45]"
      @input="$emit('update:modelValue', $event.target.value)"
    />
  </div>
</template>
