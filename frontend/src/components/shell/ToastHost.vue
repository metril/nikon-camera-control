<script setup>
import { computed } from 'vue'
import { useToastsStore } from '@/stores/toasts'

const toasts = useToastsStore()
/** The store owns lifetimes: errors are sticky, others auto-dismiss. */
const shown = computed(() => toasts.items)
const dismiss = (id) => toasts.dismiss(id)
const TONES = {
  error: 'border-camera-danger/50 bg-[#1f1313] text-camera-text',
  warn: 'border-camera-warn/40 bg-[#1c190f] text-camera-text',
  success: 'border-camera-ok/40 bg-[#101c14] text-camera-text',
  info: 'border-camera-border bg-camera-raised text-camera-text',
}
const detail = (t) =>
  [t.code && `Code: ${t.code}`, t.requestId && `Request: ${t.requestId}`]
    .filter(Boolean)
    .join(' · ')
</script>

<template>
  <div
    class="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2"
    aria-live="polite"
    aria-atomic="false"
  >
    <div
      v-for="t in shown"
      :key="t.id"
      :role="t.kind === 'error' ? 'alert' : 'status'"
      class="pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg"
      :class="TONES[t.kind] || TONES.info"
      data-test="toast"
    >
      <div class="min-w-0 flex-1">
        <p class="break-words">{{ t.message }}</p>
        <p v-if="detail(t)" class="mt-0.5 break-all text-xs opacity-70" data-test="detail">
          {{ detail(t) }}
        </p>
      </div>
      <button
        type="button"
        aria-label="Dismiss notification"
        class="rounded px-1 text-lg leading-none opacity-70 hover:opacity-100"
        @click="dismiss(t.id)"
      >
        &times;
      </button>
    </div>
  </div>
</template>
