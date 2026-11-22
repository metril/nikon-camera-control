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
  <div class="flex flex-col gap-1">
    <label v-if="label" :for="id" class="text-xs text-camera-muted">{{ label }}</label>
    <input
      :id="id"
      :type="type"
      :value="modelValue ?? ''"
      :placeholder="placeholder"
      :disabled="disabled"
      :maxlength="maxlength"
      class="rounded-md border border-camera-border bg-camera-bg px-2 py-1.5 text-sm placeholder:text-camera-muted disabled:cursor-not-allowed disabled:opacity-50"
      @input="$emit('update:modelValue', $event.target.value)"
    />
  </div>
</template>
