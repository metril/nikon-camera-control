<script setup>
import { computed } from 'vue'
import UiIcon from './UiIcon.vue'

const props = defineProps({
  /** ok | warn | danger | info */
  tone: { type: String, default: 'info' },
  title: { type: String, default: '' },
  dismissible: Boolean,
})
defineEmits(['dismiss'])
const TONES = {
  ok: { box: 'border-camera-ok/40 bg-[#101c14]', icon: 'text-camera-ok', name: 'CircleCheck' },
  warn: {
    box: 'border-camera-warn/35 bg-[#1c190f]',
    icon: 'text-camera-warn',
    name: 'TriangleAlert',
  },
  danger: {
    box: 'border-camera-danger/40 bg-[#1f1313]',
    icon: 'text-camera-danger',
    name: 'CircleAlert',
  },
  info: { box: 'border-camera-border bg-camera-raised', icon: 'text-camera-muted', name: 'Info' },
}
const t = computed(() => TONES[props.tone] || TONES.info)
</script>

<template>
  <div
    :role="tone === 'danger' ? 'alert' : 'status'"
    class="flex items-start gap-2.5 rounded-inner border px-3.5 py-3 text-sm"
    :class="t.box"
  >
    <UiIcon :name="t.name" class="mt-px" :class="t.icon" />
    <div class="min-w-0 flex-1">
      <b v-if="title" class="block font-semibold">{{ title }}</b>
      <div class="text-camera-muted"><slot /></div>
      <div v-if="$slots.action" class="mt-2 flex flex-wrap gap-2"><slot name="action" /></div>
    </div>
    <button
      v-if="dismissible"
      type="button"
      aria-label="Dismiss"
      class="inline-flex h-6 w-6 flex-none items-center justify-center rounded text-camera-muted hover:text-camera-text"
      @click="$emit('dismiss')"
    >
      <UiIcon name="X" :size="16" />
    </button>
  </div>
</template>
