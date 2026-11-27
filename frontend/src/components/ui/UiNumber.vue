<script setup>
import { computed, ref, watch } from 'vue'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { uid } from './uid'
import UiIcon from './UiIcon.vue'
import UiKeypad from './UiKeypad.vue'

const props = defineProps({
  modelValue: { type: Number, default: null },
  label: { type: String, default: '' },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
  step: { type: Number, default: 1 },
  /** Decimals the touch keypad allows (default: from step, min, max and the value). */
  decimals: { type: Number, default: undefined },
  unit: { type: String, default: '' },
  disabled: Boolean,
  /** Snap committed values to the step grid (anchored at min, or 0). */
  snap: Boolean,
})
/** update:modelValue fires per keystroke; commit fires once when the edit is final. */
const emit = defineEmits(['update:modelValue', 'commit'])
const id = uid('number')
const { isTouch } = useLayoutMode()
const keypadOpen = ref(false)
const field = ref(null)

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

const stepDecimals = () => (String(props.step).split('.')[1] || '').length
function snapTo(n) {
  if (!props.snap || !(props.step > 0)) return n
  const anchor = props.min ?? 0
  return Number(
    (anchor + Math.round((n - anchor) / props.step) * props.step).toFixed(stepDecimals()),
  )
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
function openKeypad() {
  if (!isTouch.value || props.disabled) return
  keypadOpen.value = true
}
function onKeypad(n) {
  keypadOpen.value = false
  const c = snapTo(clamp(n))
  text.value = fmt(c)
  dirty = false
  emit('update:modelValue', c)
  emit('commit', c)
}
const atMin = computed(() => props.min != null && (parse(text.value) ?? props.min) <= props.min)
const atMax = computed(
  () => props.max != null && (parse(text.value) ?? props.min ?? 0) >= props.max,
)
function bump(dir) {
  const base = parse(text.value) ?? props.min ?? 0
  const next = snapTo(clamp(Number((base + dir * props.step).toFixed(stepDecimals()))))
  text.value = fmt(next)
  dirty = false
  emit('update:modelValue', next)
  emit('commit', next)
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <label
      v-if="label"
      :for="id"
      class="text-xs font-medium text-camera-muted [html[data-layout='touch']_&]:text-[length:var(--fs-min)]"
      >{{ label }}</label
    >
    <div class="flex items-center gap-2">
      <button
        v-if="isTouch"
        type="button"
        class="step"
        aria-label="Decrease"
        data-test="num-dec"
        :disabled="disabled || atMin"
        @click="bump(-1)"
      >
        <UiIcon name="Minus" :size="20" />
      </button>
      <div ref="field" class="relative min-w-0 flex-1">
        <input
          :id="id"
          type="text"
          :inputmode="isTouch ? 'none' : 'decimal'"
          :readonly="isTouch"
          :value="text"
          :disabled="disabled"
          :aria-valuemin="min"
          :aria-valuemax="max"
          :aria-haspopup="isTouch ? 'dialog' : undefined"
          class="ui-num h-[var(--ctl)] w-full min-w-0 rounded-control border border-camera-border bg-camera-bg pl-3 text-sm tabular-nums text-camera-text hover:border-[#4a4a4a] disabled:cursor-not-allowed disabled:opacity-[.45]"
          :class="[unit ? 'pr-11' : 'pr-3', isTouch ? 'cursor-pointer text-center' : '']"
          @input="onInput"
          @change="commit"
          @blur="commit"
          @click="openKeypad"
          @keydown.enter="isTouch ? openKeypad() : commit()"
          @keydown.up.prevent="bump(1)"
          @keydown.down.prevent="bump(-1)"
        />
        <span
          v-if="unit"
          class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[13px] text-camera-muted"
          >{{ unit }}</span
        >
      </div>
      <button
        v-if="isTouch"
        type="button"
        class="step"
        aria-label="Increase"
        data-test="num-inc"
        :disabled="disabled || atMax"
        @click="bump(1)"
      >
        <UiIcon name="Plus" :size="20" />
      </button>
    </div>
    <UiKeypad
      v-if="keypadOpen"
      :model-value="parse(text) ?? null"
      :min="min"
      :max="max"
      :step="step"
      :decimals="decimals"
      :unit="unit"
      :title="label"
      :anchor="field?.querySelector('input')"
      @confirm="onKeypad"
      @close="keypadOpen = false"
    />
  </div>
</template>

<style scoped>
.step {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.control');
  background: theme('colors.camera.raised');
  color: theme('colors.camera.text');
  cursor: pointer;
}
.step:active:not(:disabled) {
  background: theme('colors.camera.hover');
}
.step:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
/* Text input today; hide native spinners in case the type ever becomes number */
.ui-num::-webkit-outer-spin-button,
.ui-num::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.ui-num {
  -moz-appearance: textfield;
  appearance: textfield;
}
</style>
