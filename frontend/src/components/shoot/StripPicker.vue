<script setup>
/** Value picker for the exposure strip: a popover under the cell on desktop, a bottom sheet on touch. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useLayoutMode } from '@/composables/useLayoutMode'
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
})
const emit = defineEmits(['select', 'close'])

const { isTouch } = useLayoutMode()
const panel = ref(null)
const titleId = uid('picker')
const style = ref({})

function place() {
  if (isTouch.value || !props.anchor?.getBoundingClientRect) return
  const r = props.anchor.getBoundingClientRect()
  const width = props.twoLine ? 300 : 240
  style.value = {
    left: `${Math.min(window.innerWidth - width - 16, Math.max(8, r.left))}px`,
    top: `${r.bottom + 6}px`,
    maxHeight: `${Math.max(160, Math.min(340, window.innerHeight - r.bottom - 20))}px`,
  }
}

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
  const next = Math.max(0, Math.min(list.length - 1, (at < 0 ? 0 : at) + (e.key === 'ArrowDown' ? 1 : -1)))
  list[next].focus()
}

const locked = computed(() => !!props.lockedReason)
onMounted(async () => {
  place()
  await nextTick()
  const sel = panel.value?.querySelector('[aria-selected="true"]')
  sel?.scrollIntoView?.({ block: 'center' })
  ;(sel || panel.value?.querySelector('[role="option"]') || panel.value)?.focus({
    preventScroll: true,
  })
})
onBeforeUnmount(() => {
  if (props.anchor?.isConnected) props.anchor.focus?.({ preventScroll: true })
})
</script>

<template>
  <Teleport to="body">
    <div class="picker-scrim" :class="{ sheet: isTouch }" @pointerdown.self="emit('close')" />
    <div
      ref="panel"
      class="picker"
      :class="{ wide: twoLine, sheet: isTouch }"
      :style="style"
      role="dialog"
      :aria-modal="isTouch ? 'true' : undefined"
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
        </header>
      </div>
      <div class="opts" role="listbox" :aria-label="title">
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
:global(html[data-layout='touch']) .picker.sheet {
  left: 0 !important;
  right: 0;
  bottom: 0;
  top: auto !important;
  width: auto;
  max-height: 62vh !important;
  border-radius: 16px 16px 0 0;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}
:global(html[data-layout='touch']) .picker.sheet .grab {
  display: block;
  width: 40px;
  height: 4px;
  border-radius: 2px;
  background: theme('colors.camera.border');
  margin: 8px auto 0;
}
:global(html[data-layout='touch']) .picker.sheet header {
  padding: 16px 20px;
  font-size: 16px;
}
:global(html[data-layout='touch']) .picker.sheet .opts {
  padding: 6px 12px 12px;
}
:global(html[data-layout='touch']) .picker.sheet .opt {
  height: 56px;
  font-size: 18px;
  padding: 0 14px;
}
:global(html[data-layout='touch']) .picker.sheet .opt.two {
  min-height: 64px;
  height: auto;
}
</style>
