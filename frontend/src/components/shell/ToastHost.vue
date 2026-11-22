<script setup>
import { ref, watch } from 'vue'
import { useToastsStore } from '@/stores/toasts'

const toasts = useToastsStore()
/** Local list: non-error toasts follow the store's auto-dismiss; errors stay until dismissed here. */
const shown = ref([])

watch(
  () => toasts.items,
  (items) => {
    const live = new Set(items.map((t) => t.id))
    const known = new Set(shown.value.map((t) => t.id))
    const added = items.filter((t) => !known.has(t.id))
    shown.value = [...shown.value.filter((t) => t.kind === 'error' || live.has(t.id)), ...added]
  },
  { immediate: true, deep: true },
)

function dismiss(id) {
  shown.value = shown.value.filter((t) => t.id !== id)
  toasts.dismiss(id)
}
const TONES = {
  error: 'border-red-500/60 bg-red-950/90 text-red-100',
  success: 'border-green-500/60 bg-green-950/90 text-green-100',
  info: 'border-camera-border bg-camera-surface text-camera-text',
}
const detail = (t) =>
  [
    t.code && `Code: ${t.code}`,
    (t.requestId || t.request_id) && `Request: ${t.requestId || t.request_id}`,
  ]
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
