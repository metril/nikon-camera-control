<script setup>
import { ref } from 'vue'
import UiIcon from '@/components/ui/UiIcon.vue'

/** Two big source cards (radiogroup): `sources` = [{ value, icon, title, subtitle, action? }]. */
const props = defineProps({
  modelValue: { type: String, required: true },
  sources: { type: Array, required: true },
})
const emit = defineEmits(['update:modelValue'])
const root = ref(null)

function onKey(e) {
  const i = props.sources.findIndex((s) => s.value === props.modelValue)
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]
  if (!step) return
  e.preventDefault()
  const n = props.sources.length
  const next = props.sources[(i + step + n) % n]
  emit('update:modelValue', next.value)
  root.value?.querySelector(`[data-source="${next.value}"]`)?.focus()
}
</script>

<template>
  <div ref="root" role="radiogroup" aria-label="Gallery source" class="grid gap-3 sm:grid-cols-2">
    <div v-for="s in sources" :key="s.value" class="relative min-w-0">
      <button
        type="button"
        role="radio"
        :data-source="s.value"
        :aria-checked="modelValue === s.value"
        :tabindex="modelValue === s.value ? 0 : -1"
        class="flex min-h-[64px] w-full min-w-0 items-center gap-3 rounded-card border px-4 py-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-camera-accent [html[data-layout='touch']_&]:min-h-[72px]"
        :class="[
          modelValue === s.value
            ? 'border-camera-accent bg-camera-accent/15'
            : 'border-camera-border bg-camera-surface hover:bg-camera-hover',
          s.action ? 'pr-28' : '',
        ]"
        @click="emit('update:modelValue', s.value)"
        @keydown="onKey"
      >
        <UiIcon
          :name="s.icon"
          :size="28"
          :class="modelValue === s.value ? 'text-camera-accent' : 'text-camera-muted'"
        />
        <span class="min-w-0">
          <span class="block truncate text-base font-semibold">{{ s.title }}</span>
          <span class="block truncate text-[13px] text-camera-muted">{{ s.subtitle }}</span>
        </span>
      </button>
      <a
        v-if="s.action"
        :href="s.action.href"
        class="absolute right-3 top-1/2 inline-flex h-[var(--ctl-sm)] -translate-y-1/2 items-center rounded-control border border-camera-border bg-camera-raised px-3 text-[13px] hover:bg-camera-hover [html[data-layout='touch']_&]:h-11"
      >
        {{ s.action.label }}
      </a>
    </div>
  </div>
</template>
