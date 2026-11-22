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
  /** Snap committed values to the step grid (anchored at min, or 0). */
  snap: Boolean,
})
/** update:modelValue fires per keystroke; commit fires once when the edit is final. */
const emit = defineEmits(['update:modelValue', 'commit'])
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

const decimals = () => (String(props.step).split('.')[1] || '').length
function snapTo(n) {
  if (!props.snap || !(props.step > 0)) return n
  const anchor = props.min ?? 0
  return Number((anchor + Math.round((n - anchor) / props.step) * props.step).toFixed(decimals()))
}
let dirty = false

function onInput(e) {
  text.value = e.target.value
  dirty = true
  const n = parse(text.value)
  if (n !== undefined) emit('update:modelValue', n)
}
/** Enter / blur / change: normalise the text and, if edited, emit the final value once. */
function commit() {
  const n = parse(text.value)
  if (n === undefined) {
    text.value = fmt(props.modelValue)
    dirty = false
    return
  }
  const c = n === null ? null : snapTo(clamp(n))
  text.value = fmt(c)
  if (!dirty && c === (props.modelValue ?? null)) return
  emit('update:modelValue', c)
  if (dirty) emit('commit', c)
  dirty = false
}
function bump(dir) {
  const base = parse(text.value) ?? props.min ?? 0
  const next = snapTo(clamp(Number((base + dir * props.step).toFixed(decimals()))))
  text.value = fmt(next)
  dirty = false
  emit('update:modelValue', next)
  emit('commit', next)
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
        @keydown.enter="commit"
        @keydown.up.prevent="bump(1)"
        @keydown.down.prevent="bump(-1)"
      />
      <span v-if="unit" class="text-xs text-camera-muted">{{ unit }}</span>
    </div>
  </div>
</template>
