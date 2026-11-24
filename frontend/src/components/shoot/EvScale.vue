<script setup>
/** −3 to +3 EV scale with one marker per bracket frame. */
import { computed } from 'vue'
import { fmtEV } from './helpers'

const props = defineProps({ offsets: { type: Array, required: true } })

const x = (v) => 20 + ((v + 3) / 6) * 280
const ticks = Array.from({ length: 19 }, (_, i) => {
  const v = (i - 9) / 3
  const big = i % 3 === 0
  return { v, big, x: x(v), label: v === 0 ? '0' : `${v > 0 ? '+' : '−'}${Math.abs(v)}` }
})
const marks = computed(() =>
  props.offsets.map((v) => x(Math.max(-3, Math.min(3, v)))),
)
const description = computed(() => `Bracket frames: ${props.offsets.map(fmtEV).join(', ')} EV`)
</script>

<template>
  <svg
    class="block h-auto w-full"
    viewBox="0 0 320 56"
    role="img"
    :aria-label="description"
    data-testid="ev-scale"
  >
    <line x1="20" x2="300" y1="36" y2="36" class="stroke-camera-border" />
    <template v-for="t in ticks" :key="t.v">
      <line :x1="t.x" :x2="t.x" :y1="t.big ? 24 : 28" y2="36" class="stroke-camera-faint" />
      <text
        v-if="t.big"
        :x="t.x"
        y="50"
        text-anchor="middle"
        font-size="10"
        class="fill-camera-muted font-mono"
      >
        {{ t.label }}
      </text>
    </template>
    <path
      v-for="(m, i) in marks"
      :key="i"
      :d="`M${m} 20 l-5 -8 h10 z`"
      class="fill-camera-accent"
      data-testid="ev-mark"
    />
  </svg>
</template>
