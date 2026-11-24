<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { uid } from './uid'
import UiIcon from './UiIcon.vue'

defineOptions({ inheritAttrs: false })
const props = defineProps({
  open: Boolean,
  title: { type: String, default: '' },
  /** Additive: false hides the close button and ignores Esc (e.g. mandatory prompts). */
  closable: { type: Boolean, default: true },
  /** 'center' (default) or 'side' (right-hand sheet, full height). */
  variant: { type: String, default: 'center' },
})
const emit = defineEmits(['close'])

const panel = ref(null)
const titleId = uid('modal-title')
let opener = null

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
const focusables = () => (panel.value ? [...panel.value.querySelectorAll(FOCUSABLE)] : [])

function onKeydown(e) {
  if (e.key === 'Escape' && props.closable) {
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
      await nextTick()
      const mark = panel.value?.querySelector('[data-autofocus]')
      const inner = mark?.matches(FOCUSABLE) ? mark : mark?.querySelector(FOCUSABLE)
      ;(inner || focusables()[0] || panel.value)?.focus()
    } else {
      opener?.focus?.()
      opener = null
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => opener?.focus?.())
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex bg-black/70"
      :class="variant === 'side' ? 'justify-end' : 'items-center justify-center p-4'"
      @mousedown.self="closable && emit('close')"
    >
      <div
        ref="panel"
        v-bind="$attrs"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        tabindex="-1"
        class="flex flex-col border border-camera-border bg-camera-surface shadow-xl"
        :class="
          variant === 'side'
            ? 'h-full w-full max-w-md border-y-0 border-r-0'
            : 'max-h-full w-full max-w-lg rounded-card'
        "
        @keydown="onKeydown"
      >
        <header
          class="flex items-center justify-between gap-2 border-b border-camera-border px-4 py-3"
        >
          <h2 :id="titleId" class="text-base font-semibold">{{ title }}</h2>
          <button
            v-if="closable"
            type="button"
            aria-label="Close"
            class="inline-flex h-8 w-8 items-center justify-center rounded text-camera-muted hover:text-camera-text"
            @click="emit('close')"
          >
            <UiIcon name="X" :size="18" />
          </button>
        </header>
        <div class="flex-1 overflow-y-auto p-4"><slot /></div>
        <footer
          v-if="$slots.footer"
          class="flex flex-wrap justify-end gap-2 border-t border-camera-border px-4 py-3"
        >
          <slot name="footer" />
        </footer>
      </div>
    </div>
  </Teleport>
</template>
