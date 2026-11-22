<script setup>
import { computed } from 'vue'
import { uid } from './uid'

const props = defineProps({
  modelValue: { type: [String, Number, Boolean], default: null },
  options: { type: Array, default: () => [] },
  label: { type: String, default: '' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const id = uid('select')
const items = computed(() =>
  props.options.map((o) =>
    o !== null && typeof o === 'object' ? o : { value: o, label: String(o) },
  ),
)
function onChange(e) {
  const item = items.value[e.target.selectedIndex]
  if (item) emit('update:modelValue', item.value)
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <label v-if="label" :for="id" class="text-xs text-camera-muted">{{ label }}</label>
    <select
      :id="id"
      :disabled="disabled"
      class="rounded-md border border-camera-border bg-camera-bg px-2 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
      @change="onChange"
    >
      <option
        v-for="o in items"
        :key="String(o.value)"
        :value="String(o.value)"
        :selected="o.value === modelValue"
      >
        {{ o.label }}
      </option>
    </select>
  </div>
</template>
