<script setup>
/** Value picker for the exposure strip: a popover under the cell (desktop, and touch landscape with
 * bigger options and step buttons), a bottom sheet on touch portrait. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLayoutMode, useTouchLandscape } from '@/composables/useLayoutMode'
import UiIcon from '@/components/ui/UiIcon.vue'
import { uid } from '@/components/ui/uid'

const props = defineProps({
  title: { type: String, required: true },
  /** [{ value, label, sub?, selected? }] */
  options: { type: Array, default: () => [] },
  anchor: { type: Object, default: null },
  /** Why the options cannot be changed (shown beside the title); options are then disabled. */
  lockedReason: { type: String, default: '' },
  /** Options carry a description: two-line rows in a wider panel. */
  twoLine: Boolean,
  emptyText: { type: String, default: 'Nothing to choose.' },
  /** Touch landscape popover: show -/+ buttons that step to the previous / next value. */
  steppable: Boolean,
})
const emit = defineEmits(['select', 'close', 'step'])

const { isTouch } = useLayoutMode()
const landscape = useTouchLandscape()
/** Touch portrait: a bottom sheet. Desktop and touch landscape: a popover under the cell. */
const sheet = computed(() => isTouch.value && !landscape.value)
const big = computed(() => isTouch.value && landscape.value) // popover with 56px options
/** Columns of options in the touch popover: 2 for few values, up to 4 for long lists. */
const cols = computed(() => {
  if (props.twoLine) return 2
  const n = props.options.length
  return n > 24 ? 4 : n > 8 ? 3 : 2
})
const panel = ref(null)
const titleId = uid('picker')
const style = ref({})

const WIDTH = { 2: 300, 3: 400, 4: 500 } // touch popover width by column count
function place() {
  if (sheet.value || !props.anchor?.getBoundingClientRect) return
  const r = props.anchor.getBoundingClientRect()
  const width = big.value ? WIDTH[cols.value] : props.twoLine ? 300 : 240
  const below = window.innerHeight - r.bottom - 20
  const above = r.top - 20
  const flip = below < 160 && above > below // too little room under the cell: open upwards
  // touch: at most 60% of the live view's height
  const lv = big.value
    ? document
        .querySelector('[aria-label="Live view"], [data-test="lv-gate"]')
        ?.getBoundingClientRect().height
    : 0
  const cap = lv ? lv * 0.6 : 340
  style.value = {
    left: `${Math.min(window.innerWidth - width - 16, Math.max(8, r.left))}px`,
    ...(flip ? { bottom: `${window.innerHeight - r.top + 6}px` } : { top: `${r.bottom + 6}px` }),
    maxHeight: `${Math.max(80, Math.min(cap, flip ? above : below))}px`,
    ...(big.value ? { width: `${width}px` } : {}),
  }
}
watch([sheet, big], () => {
  if (sheet.value) style.value = {}
  else place()
})

const rows = () => [...(panel.value?.querySelectorAll('[role="option"]:not(:disabled)') || [])]
function onKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    e.preventDefault()
    emit('close')
    return
  }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  e.preventDefault()
  const list = rows()
  if (!list.length) return
  const at = list.indexOf(document.activeElement)
  const next = Math.max(
    0,
    Math.min(list.length - 1, (at < 0 ? 0 : at) + (e.key === 'ArrowDown' ? 1 : -1)),
  )
  list[next].focus()
}

// capture-phase: any scrolling ancestor moves the anchor, but the panel's own list does not
const onScroll = (e) => {
  if (!panel.value?.contains(e.target)) place()
}

const locked = computed(() => !!props.lockedReason)
onMounted(async () => {
  place()
  window.addEventListener('resize', place)
  window.addEventListener('scroll', onScroll, true)
  await nextTick()
  const sel = panel.value?.querySelector('[aria-selected="true"]')
  sel?.scrollIntoView?.({ block: 'center' })
  ;(sel || panel.value?.querySelector('[role="option"]') || panel.value)?.focus({
    preventScroll: true,
  })
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', place)
  window.removeEventListener('scroll', onScroll, true)
  if (props.anchor?.isConnected) props.anchor.focus?.({ preventScroll: true })
})
</script>

<template>
  <Teleport to="body">
    <div class="picker-scrim" :class="{ sheet }" @pointerdown.self="emit('close')" />
    <div
      ref="panel"
      class="picker"
      :class="{ wide: twoLine, sheet, big }"
      :style="style"
      role="dialog"
      :aria-modal="sheet ? 'true' : undefined"
      :aria-labelledby="titleId"
      tabindex="-1"
      data-test="picker"
      @keydown="onKeydown"
    >
      <div>
        <div class="grab" aria-hidden="true" />
        <header>
          <span :id="titleId">{{ title }}</span>
          <span v-if="lockedReason" class="note" data-test="picker-locked">{{ lockedReason }}</span>
          <span v-if="big && steppable" class="steps">
            <button
              type="button"
              aria-label="Previous value"
              data-test="picker-prev"
              :disabled="locked"
              @click="emit('step', -1)"
            >
              <UiIcon name="Minus" :size="20" />
            </button>
            <button
              type="button"
              aria-label="Next value"
              data-test="picker-next"
              :disabled="locked"
              @click="emit('step', 1)"
            >
              <UiIcon name="Plus" :size="20" />
            </button>
          </span>
        </header>
      </div>
      <div
        class="opts"
        :class="{ grid: big }"
        :style="big ? { '--cols': cols } : undefined"
        role="listbox"
        :aria-label="title"
      >
        <button
          v-for="o in options"
          :key="String(o.value)"
          type="button"
          role="option"
          class="opt"
          :class="{ two: twoLine }"
          :aria-selected="!!o.selected"
          :disabled="locked || o.disabled"
          @click="emit('select', o.value)"
        >
          <span class="lbl">{{ o.label }}</span>
          <span v-if="o.sub" class="sub">{{ o.sub }}</span>
        </button>
        <p v-if="!options.length" class="empty">{{ emptyText }}</p>
      </div>
      <div v-if="$slots.footer" class="foot"><slot name="footer" /></div>
    </div>
  </Teleport>
</template>

<style scoped>
.picker-scrim {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: transparent;
}
.picker-scrim.sheet {
  background: rgba(0, 0, 0, 0.55);
}
.picker {
  position: fixed;
  z-index: 41;
  width: 240px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.card');
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.55);
}
.picker.wide {
  width: 300px;
}
.picker header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid theme('colors.camera.subtle');
  font-weight: 600;
}
.note {
  font-weight: 400;
  font-size: 12px;
  color: theme('colors.camera.muted');
}
.opts {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.opt {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 36px;
  padding: 0 10px;
  border: 0;
  background: none;
  border-radius: theme('borderRadius.control');
  cursor: pointer;
  text-align: left;
  font:
    500 14px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  font-variant-numeric: tabular-nums;
  color: theme('colors.camera.text');
}
.opt:hover:not(:disabled),
.opt:focus-visible {
  background: theme('colors.camera.raised');
}
.opt:focus-visible {
  outline-offset: -2px;
}
.opt:active:not(:disabled) {
  background: theme('colors.camera.hover');
}
.opt:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
.opt[aria-selected='true'] {
  color: theme('colors.camera.accent');
}
.opt .sub {
  font:
    12px system-ui,
    sans-serif;
  color: theme('colors.camera.muted');
  white-space: nowrap;
}
.opt.two {
  height: auto;
  min-height: 48px;
  padding: 8px 10px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
}
.opt.two .lbl {
  font-family: system-ui, sans-serif;
}
.opt.two .sub {
  white-space: normal;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.empty {
  padding: 12px;
  font-size: 13px;
  color: theme('colors.camera.muted');
}
.foot {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  border-top: 1px solid theme('colors.camera.subtle');
}
.grab {
  display: none;
}
html[data-layout='touch'] .picker.big header {
  padding: 8px 12px;
  min-height: 68px;
  font-size: 16px;
}
.steps {
  display: inline-flex;
  gap: var(--tap-gap, 8px);
  margin-left: auto;
}
.steps button {
  display: inline-flex;
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
.steps button:active:not(:disabled) {
  background: theme('colors.camera.hover');
}
.steps button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
html[data-layout='touch'] .picker.big .opts.grid {
  display: grid;
  grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
  gap: 4px;
  align-content: start;
  padding: 8px;
}
html[data-layout='touch'] .picker.big .opt {
  height: 56px;
  font-size: 16px;
  padding: 0 12px;
}
html[data-layout='touch'] .picker.big .opt.two {
  min-height: 56px;
  height: auto;
}
html[data-layout='touch'] .picker.big .note,
html[data-layout='touch'] .picker.big .opt .sub,
html[data-layout='touch'] .picker.big .empty {
  font-size: var(--fs-min, 13px);
}
html[data-layout='touch'] .picker.sheet {
  left: 0 !important;
  right: 0;
  bottom: 0;
  top: auto !important;
  width: auto;
  max-height: 62vh !important;
  border-radius: 16px 16px 0 0;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
@media (min-width: 900px) {
  html[data-layout='touch'] .picker.sheet {
    width: min(100%, 560px);
    margin-inline: auto;
    border-radius: 16px 16px 0 0;
  }
}
html[data-layout='touch'] .picker.sheet .grab {
  display: block;
  width: 40px;
  height: 4px;
  border-radius: 2px;
  background: theme('colors.camera.border');
  margin: 8px auto 0;
}
html[data-layout='touch'] .picker.sheet header {
  padding: 16px 20px;
  font-size: 16px;
}
html[data-layout='touch'] .picker.sheet .opts {
  padding: 6px 12px 12px;
}
html[data-layout='touch'] .picker.sheet .opt {
  height: 56px;
  font-size: 18px;
  padding: 0 14px;
}
html[data-layout='touch'] .picker.sheet .opt.two {
  min-height: 64px;
  height: auto;
}
html[data-layout='touch'] .note,
html[data-layout='touch'] .opt .sub {
  font-size: var(--fs-min);
}
</style>
