<script setup>
import { computed } from 'vue'
import { useToastsStore } from '@/stores/toasts'
import UiIcon from '@/components/ui/UiIcon.vue'

const toasts = useToastsStore()
/** The store owns lifetimes: errors are sticky, others auto-dismiss. */
const shown = computed(() => toasts.items)
const dismiss = (id) => toasts.dismiss(id)
const TONES = {
  error: { icon: 'CircleAlert', cls: 'text-camera-danger' },
  warn: { icon: 'TriangleAlert', cls: 'text-camera-warn' },
  success: { icon: 'CircleCheck', cls: 'text-camera-ok' },
  info: { icon: 'Info', cls: 'text-camera-muted' },
}
const tone = (t) => TONES[t.kind] || TONES.info
const detail = (t) =>
  [t.code && `Code: ${t.code}`, t.requestId && `Request: ${t.requestId}`]
    .filter(Boolean)
    .join(' · ')
</script>

<template>
  <div class="toasts" aria-live="polite" aria-atomic="false">
    <div
      v-for="t in shown"
      :key="t.id"
      :role="t.kind === 'error' ? 'alert' : 'status'"
      class="toast"
      data-test="toast"
    >
      <UiIcon :name="tone(t).icon" :class="tone(t).cls" />
      <div class="min-w-0">
        <p class="break-words">{{ t.message }}</p>
        <details v-if="detail(t)" class="mt-1 text-xs text-camera-muted">
          <summary class="cursor-pointer">Technical details</summary>
          <p class="break-all" data-test="detail">{{ detail(t) }}</p>
        </details>
      </div>
      <button type="button" class="x" aria-label="Dismiss notification" @click="dismiss(t.id)">
        <UiIcon name="X" :size="16" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.toasts {
  pointer-events: none;
  position: fixed;
  right: 16px;
  bottom: calc(16px + var(--nav, 0px) + env(safe-area-inset-bottom, 0px));
  z-index: 60;
  display: grid;
  gap: 8px;
  width: min(360px, calc(100% - 32px));
}
.toast {
  pointer-events: auto;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  padding: 8px 8px 8px 12px;
  background: theme('colors.camera.raised');
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.inner');
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  font-size: 14px;
  animation: tin 180ms ease-out;
}
.toast > :first-child {
  margin-top: 7px;
}
.toast p {
  margin: 0;
  padding: 6px 0;
}
.x {
  width: var(--ctl-sm);
  height: var(--ctl-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: theme('borderRadius.control');
  background: none;
  color: theme('colors.camera.muted');
  cursor: pointer;
}
.x:hover {
  color: theme('colors.camera.text');
  background: theme('colors.camera.hover');
}
@keyframes tin {
  from {
    transform: translateY(8px);
    opacity: 0;
  }
}
html[data-layout='touch'] .toasts {
  left: 50%;
  right: auto;
  transform: translateX(-50%);
}
</style>
