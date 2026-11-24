<script setup>
/** Focus pill for the live view: large and small steps nearer and farther, and autofocus. */
import { computed, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useFocusStore } from '@/stores/focus'
import { useToastsStore } from '@/stores/toasts'
import { leaseOwner } from '@/labels'
import UiIcon from '@/components/ui/UiIcon.vue'
import { useHoldRepeat } from './useHoldRepeat'

const SMALL = 50
const LARGE = 400

const camera = useCameraStore()
const focus = useFocusStore()
const toasts = useToastsStore()

const reason = computed(() => {
  if (!camera.connected) return 'Camera not connected'
  if (camera.leasedBy) return `Busy: ${leaseOwner(camera.leasedBy)}`
  return ''
})
const off = computed(() => !!reason.value)

// Negative steps move focus nearer, positive farther. Hold a button to repeat.
const buttons = [
  { icon: 'ChevronsLeft', aria: 'Large step nearer', steps: -LARGE },
  { icon: 'ChevronLeft', aria: 'Small step nearer', steps: -SMALL },
  { icon: 'ChevronRight', aria: 'Small step farther', steps: SMALL },
  { icon: 'ChevronsRight', aria: 'Large step farther', steps: LARGE },
]
let pending = 0
const hold = useHoldRepeat(() => focus.manual(pending), { onError: (e) => toasts.error(e) })
const press = (b) => {
  pending = b.steps
  hold.start()
}
const key = (b) => {
  pending = b.steps
  hold.once()
}

async function autofocus() {
  try {
    const r = await focus.autofocus()
    if (r?.focused === false) toasts.warn('Focus failed. Try a different focus point.')
  } catch (e) {
    toasts.error(e)
  }
}

// the position is only readable with a connected camera (503 otherwise)
watch(
  () => camera.connected,
  (on) => on && focus.fetchStatus().catch(() => {}),
  { immediate: true },
)
</script>

<template>
  <div class="pill" role="toolbar" aria-label="Focus" :title="reason || undefined">
    <template v-for="(b, i) in buttons" :key="b.aria">
      <button
        v-if="i === 2"
        type="button"
        class="af"
        :disabled="off"
        title="Autofocus at the focus point"
        @click="autofocus"
      >
        <UiIcon name="Focus" :size="16" /><span class="lbl">Autofocus</span>
      </button>
      <button
        type="button"
        :aria-label="b.aria"
        :title="b.aria"
        :disabled="off"
        @pointerdown.prevent="press(b)"
        @pointerup="hold.stop()"
        @pointerleave="hold.stop()"
        @pointercancel="hold.stop()"
        @click="$event.detail === 0 && key(b)"
      >
        <UiIcon :name="b.icon" :size="16" />
      </button>
    </template>
  </div>
</template>

<style scoped>
.pill {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 9999px;
  background: rgba(21, 21, 21, 0.82);
  border: 1px solid theme('colors.camera.border');
  backdrop-filter: blur(6px);
}
button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: var(--ctl-sm);
  min-width: var(--ctl-sm);
  padding: 0 8px;
  border: 0;
  border-radius: 9999px;
  background: none;
  color: theme('colors.camera.muted');
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  touch-action: none;
}
button:hover:not(:disabled) {
  color: theme('colors.camera.text');
  background: theme('colors.camera.raised');
}
button:active:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  color: theme('colors.camera.text');
}
button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.af {
  color: theme('colors.camera.text');
  border: 1px solid theme('colors.camera.border');
  margin: 0 4px;
  padding: 0 12px;
}
@media (max-width: 1100px) {
  .lbl {
    display: none;
  }
}
</style>
