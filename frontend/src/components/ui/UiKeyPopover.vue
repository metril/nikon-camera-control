<script setup>
/** Popover shell for on-screen input (keypad, later a keyboard): a scrim and a panel anchored under
 * an element, flipping above it when there is no room. Esc and a tap outside close it. */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  anchor: { type: Object, default: null },
})
const emit = defineEmits(['close', 'key'])
const panel = ref(null)
const style = ref({})
const MARGIN = 8

function place() {
  const el = panel.value
  if (!el || !props.anchor?.getBoundingClientRect) return
  const r = props.anchor.getBoundingClientRect()
  const w = el.offsetWidth
  const h = el.offsetHeight
  const below = window.innerHeight - r.bottom - MARGIN
  const above = r.top - MARGIN
  const up = h > below && above > below
  const top = up
    ? Math.max(MARGIN, r.top - 6 - h)
    : Math.min(r.bottom + 6, Math.max(MARGIN, window.innerHeight - h - MARGIN))
  const left = Math.min(
    window.innerWidth - w - MARGIN,
    Math.max(MARGIN, r.left + r.width / 2 - w / 2),
  )
  style.value = { top: `${top}px`, left: `${left}px` }
}
// Keys belong to the open popover: nothing bubbles to app hotkeys (Space, G, T ...)
function onKeydown(e) {
  e.stopPropagation()
  if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
  } else emit('key', e)
}
onMounted(async () => {
  await nextTick()
  place()
  panel.value?.focus({ preventScroll: true })
  window.addEventListener('resize', place)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', place)
  if (props.anchor?.isConnected) props.anchor.focus?.({ preventScroll: true })
})
</script>

<template>
  <Teleport to="body">
    <div class="kp-scrim" @pointerdown.self="emit('close')" />
    <div
      ref="panel"
      class="kp"
      :style="style"
      role="dialog"
      aria-modal="true"
      :aria-label="title || undefined"
      tabindex="-1"
      data-test="key-popover"
      @keydown="onKeydown"
    >
      <slot />
    </div>
  </Teleport>
</template>

<style scoped>
.kp-scrim {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: transparent;
}
.kp {
  position: fixed;
  z-index: 41;
  padding: 12px;
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.card');
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.55);
}
.kp:focus {
  outline: none;
}
</style>
