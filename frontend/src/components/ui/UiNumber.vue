<script setup>
import { ref, watch } from 'vue'
import { uid } from './uid'

const props = defineProps({
  modelValue: { type: Number, default: null },
  label: { type: String, default: '' },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
  step: { type: Number, default: 1 },
  unit: { type: String, default: '' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const id = uid('number')

const fmt = (v) => (v == null || !Number.isFinite(v) ? '' : String(v))
const text = ref(fmt(props.modelValue))

/** Finite number or null; never NaN/Infinity. */
function parse(raw) {
  const s = String(raw).trim().replace(',', '.')
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) ? n : undefined
}
const clamp = (n) => {
  if (props.min != null && n < props.min) n = props.min
  if (props.max != null && n > props.max) n = props.max
  return n
}

watch(
  () => props.modelValue,
  (v) => {
    if (parse(text.value) !== (v ?? null)) text.value = fmt(v)
  },
)

function onInput(e) {
  text.value = e.target.value
  const n = parse(text.value)
  if (n !== undefined) emit('update:modelValue', n)
}
function commit() {
  const n = parse(text.value)
  if (n === undefined) {
    text.value = fmt(props.modelValue)
    return
  }
  const c = n === null ? null : clamp(n)
  text.value = fmt(c)
  emit('update:modelValue', c)
}
function bump(dir) {
  const base = parse(text.value) ?? props.min ?? 0
  const decimals = (String(props.step).split('.')[1] || '').length
  const next = clamp(Number((base + dir * props.step).toFixed(decimals)))
  text.value = fmt(next)
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="flex flex-col gap-1">
    <label v-if="label" :for="id" class="text-xs text-camera-muted">{{ label }}</label>
    <div class="flex items-center gap-2">
      <input
        :id="id"
        type="text"
        inputmode="decimal"
        :value="text"
        :disabled="disabled"
        :aria-valuemin="min"
        :aria-valuemax="max"
        class="min-w-0 flex-1 rounded-md border border-camera-border bg-camera-bg px-2 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        @input="onInput"
        @change="commit"
        @blur="commit"
        @keydown.up.prevent="bump(1)"
        @keydown.down.prevent="bump(-1)"
      />
      <span v-if="unit" class="text-xs text-camera-muted">{{ unit }}</span>
    </div>
  </div>
</template>
