<script setup>
import { computed } from 'vue'
const props = defineProps({
  value: { type: Number, default: null },
  label: { type: String, default: '' },
})
const pct = computed(() =>
  props.value == null || !Number.isFinite(props.value)
    ? null
    : Math.round(Math.min(1, Math.max(0, props.value)) * 100),
)
</script>

<template>
  <div>
    <div v-if="label" class="mb-1 flex justify-between text-xs text-camera-muted">
      <span>{{ label }}</span>
      <span v-if="pct !== null">{{ pct }}%</span>
    </div>
    <div
      role="progressbar"
      :aria-label="label || 'Progress'"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="pct ?? undefined"
      class="h-2 overflow-hidden rounded-full bg-camera-border"
    >
      <div
        v-if="pct !== null"
        class="h-full rounded-full bg-camera-accent transition-[width] motion-reduce:transition-none"
        :style="{ width: pct + '%' }"
      />
      <div
        v-else
        class="h-full w-1/3 animate-pulse rounded-full bg-camera-accent motion-reduce:animate-none"
      />
    </div>
  </div>
</template>
