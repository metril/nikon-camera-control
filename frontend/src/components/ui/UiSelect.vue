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
  <div class="flex flex-col gap-1.5">
    <label v-if="label" :for="id" class="text-xs font-medium text-camera-muted">{{ label }}</label>
    <select
      :id="id"
      :disabled="disabled"
      class="ui-select h-[var(--ctl)] w-full min-w-0 appearance-none rounded-control border border-camera-border bg-camera-bg pl-3 pr-9 text-sm text-camera-text hover:border-[#4a4a4a] disabled:cursor-not-allowed disabled:opacity-[.45]"
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

<style scoped>
.ui-select {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23a3a3a3' stroke-width='2' stroke-linecap='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 12px center;
}
</style>
