<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { uid } from './uid'

defineOptions({ inheritAttrs: false })
const props = defineProps({
  open: Boolean,
  /** Element (or component instance) the popover hangs from. Without it the popover is centred. */
  anchor: { type: Object, default: null },
  title: { type: String, default: '' },
  /** Preferred side; flips when it does not fit. */
  placement: { type: String, default: 'bottom', validator: (v) => ['bottom', 'top'].includes(v) },
})
const emit = defineEmits(['close'])

const panel = ref(null)
const pos = ref({ top: 0, left: 0, side: 'bottom', ready: false })
const titleId = uid('popover-title')
const GAP = 8
const MARGIN = 8
let opener = null

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
const focusables = () => (panel.value ? [...panel.value.querySelectorAll(FOCUSABLE)] : [])
const anchorEl = () => props.anchor?.$el || props.anchor || null

/** Placement maths: prefer one side, flip when the other has more room, clamp into the viewport. */
function place(a, p, vw, vh, preferred) {
  const room = { bottom: vh - a.bottom - GAP - MARGIN, top: a.top - GAP - MARGIN }
  const other = preferred === 'bottom' ? 'top' : 'bottom'
  const side = room[preferred] >= p.height || room[preferred] >= room[other] ? preferred : other
  let top = side === 'bottom' ? a.bottom + GAP : a.top - GAP - p.height
  top = Math.max(MARGIN, Math.min(top, vh - p.height - MARGIN))
  const left = Math.max(MARGIN, Math.min(a.left, vw - p.width - MARGIN))
  return { top, left, side }
}

function reposition() {
  if (!panel.value) return
  const a = anchorEl()?.getBoundingClientRect?.()
  const r = panel.value.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  if (!a) {
    pos.value = {
      top: Math.max(MARGIN, (vh - r.height) / 2),
      left: Math.max(MARGIN, (vw - r.width) / 2),
      side: 'center',
      ready: true,
    }
    return
  }
  pos.value = { ...place(a, r, vw, vh, props.placement), ready: true }
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    emit('close')
    return
  }
  if (e.key !== 'Tab') return
  const els = focusables()
  if (!els.length) {
    e.preventDefault()
    panel.value?.focus()
    return
  }
  const first = els[0]
  const last = els[els.length - 1]
  const active = document.activeElement
  if (e.shiftKey && (active === first || active === panel.value)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    first.focus()
  } else if (!panel.value.contains(active)) {
    e.preventDefault()
    first.focus()
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      opener = document.activeElement
      pos.value = { ...pos.value, ready: false }
      await nextTick()
      reposition()
      window.addEventListener('resize', reposition)
      const mark = panel.value?.querySelector('[data-autofocus]')
      const inner = mark?.matches(FOCUSABLE) ? mark : mark?.querySelector(FOCUSABLE)
      ;(inner || focusables()[0] || panel.value)?.focus()
    } else {
      window.removeEventListener('resize', reposition)
      opener?.focus?.()
      opener = null
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  window.removeEventListener('resize', reposition)
  if (props.open) opener?.focus?.()
})
defineExpose({ reposition, place })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 bg-black/50"
      data-test="popover-scrim"
      @mousedown.self="emit('close')"
    >
      <div
        ref="panel"
        v-bind="$attrs"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        tabindex="-1"
        data-test="popover"
        :data-side="pos.side"
        class="fixed flex max-h-[calc(100dvh-1rem)] w-[min(28rem,calc(100vw-1rem))] flex-col overflow-hidden rounded-card border border-camera-border bg-camera-surface shadow-xl"
        :style="{
          top: `${pos.top}px`,
          left: `${pos.left}px`,
          visibility: pos.ready ? 'visible' : 'hidden',
        }"
        @keydown="onKeydown"
      >
        <header
          v-if="title"
          class="flex items-center justify-between gap-2 border-b border-camera-border px-3 py-2"
        >
          <h2 :id="titleId" class="text-sm font-semibold">{{ title }}</h2>
          <button
            type="button"
            aria-label="Close"
            class="rounded-control px-2 text-xl leading-none text-camera-muted hover:text-camera-text"
            @click="emit('close')"
          >
            &times;
          </button>
        </header>
        <div class="scroll-panel p-3"><slot /></div>
      </div>
    </div>
  </Teleport>
</template>
