<script setup>
/** Numeric keypad popover: 0-9, decimal point, sign, backspace and OK (56px keys). Respects the
 * min/max range and the step's decimals; a hardware keyboard works too. Emits `confirm` with the
 * clamped number, or `close`. The caller snaps it to its own step grid. */
import { computed, ref } from 'vue'
import UiKey from './UiKey.vue'
import UiKeyPopover from './UiKeyPopover.vue'

const props = defineProps({
  modelValue: { type: Number, default: null },
  min: { type: Number, default: undefined },
  max: { type: Number, default: undefined },
  step: { type: Number, default: 1 },
  /** Decimal places allowed; default: the most any of step, min, max or the value has. */
  decimals: { type: Number, default: undefined },
  unit: { type: String, default: '' },
  title: { type: String, default: '' },
  anchor: { type: Object, default: null },
})
const emit = defineEmits(['confirm', 'close'])

const buf = ref('') // empty: the first key replaces the current value
const places = (n) => (n == null ? 0 : (String(n).split('.')[1] || '').length)
const decimals = computed(
  () =>
    props.decimals ??
    Math.max(places(props.step), places(props.min), places(props.max), places(props.modelValue)),
)
const canDecimal = computed(() => decimals.value > 0)
const canSign = computed(() => !(props.min != null && props.min >= 0))
const shown = computed(
  () => buf.value || (props.modelValue == null ? '' : String(props.modelValue)),
)
const range = computed(() => {
  const { min, max } = props
  if (min != null && max != null) return `${min} – ${max}`
  if (min != null) return `min ${min}`
  if (max != null) return `max ${max}`
  return ''
})

function digit(d) {
  const neg = buf.value.startsWith('-')
  let body = neg ? buf.value.slice(1) : buf.value
  if (body === '0') body = ''
  const frac = body.split('.')[1]
  if (frac != null && frac.length >= decimals.value) return
  buf.value = (neg ? '-' : '') + body + d
}
function dot() {
  if (!canDecimal.value || buf.value.includes('.')) return
  const neg = buf.value.startsWith('-')
  const body = neg ? buf.value.slice(1) : buf.value
  buf.value = (neg ? '-' : '') + (body || '0') + '.'
}
function sign() {
  if (!canSign.value) return
  buf.value = buf.value.startsWith('-') ? buf.value.slice(1) : '-' + buf.value
}
const back = () => (buf.value = buf.value.slice(0, -1))
function ok() {
  const n = Number(buf.value)
  if (buf.value === '' || buf.value === '-' || !Number.isFinite(n)) return emit('close')
  let v = n
  if (props.min != null && v < props.min) v = props.min
  if (props.max != null && v > props.max) v = props.max
  emit('confirm', v)
}
function onKeydown(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return
  if (/^[0-9]$/.test(e.key)) digit(e.key)
  else if (e.key === '.' || e.key === ',') dot()
  else if (e.key === '-') sign()
  else if (e.key === 'Backspace') back()
  else if (e.key === 'Enter') ok()
  else return
  e.preventDefault()
}
</script>

<template>
  <UiKeyPopover :anchor="anchor" :title="title || 'Keypad'" @close="emit('close')" @key="onKeydown">
    <div class="pad" data-test="keypad">
      <div class="disp" aria-live="polite">
        <span class="val tabular-nums" :class="{ ghost: !buf }" data-test="keypad-value">{{
          shown || '0'
        }}</span>
        <span v-if="unit" class="unit">{{ unit }}</span>
      </div>
      <p v-if="range" class="range" data-test="keypad-range">{{ range }}</p>
      <div class="grid3">
        <UiKey
          v-for="d in ['7', '8', '9', '4', '5', '6', '1', '2', '3']"
          :key="d"
          @click="digit(d)"
          >{{ d }}</UiKey
        >
        <UiKey :disabled="!canSign" aria-label="Plus or minus" data-test="key-sign" @click="sign"
          >±</UiKey
        >
        <UiKey @click="digit('0')">0</UiKey>
        <UiKey :disabled="!canDecimal" aria-label="Decimal point" data-test="key-dot" @click="dot"
          >.</UiKey
        >
        <UiKey variant="quiet" aria-label="Backspace" data-test="key-back" @click="back">⌫</UiKey>
        <UiKey variant="accent" class="okkey" data-test="key-ok" @click="ok">OK</UiKey>
      </div>
    </div>
  </UiKeyPopover>
</template>

<style scoped>
.pad {
  display: grid;
  gap: 8px;
  width: 200px;
}
.disp {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 6px;
  min-height: 40px;
  padding: 6px 10px;
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.control');
  background: theme('colors.camera.bg');
}
.val {
  font:
    500 24px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
}
.val.ghost {
  color: theme('colors.camera.muted');
}
.unit,
.range {
  font-size: var(--fs-min, 13px);
  color: theme('colors.camera.muted');
}
.range {
  margin: -2px 0 0;
  text-align: right;
}
.grid3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.okkey {
  grid-column: span 2;
}
</style>
