<script setup>
/** Luminance histogram with clipping percentages. Purely presentational. */
import { ref, watch, onMounted } from 'vue'
import { COLORS } from './analysis.js'

const props = defineProps({
  /** { bins: Uint32Array(256), lo, hi } from computeHistogram, or null */
  histogram: { type: Object, default: null },
})
const cv = ref(null)

function draw() {
  const ctx = cv.value?.getContext?.('2d')
  const h = props.histogram
  if (!ctx) return
  ctx.clearRect(0, 0, 256, 70)
  if (!h) return
  let max = 0
  for (let i = 2; i < 253; i++) if (h.bins[i] > max) max = h.bins[i]
  ctx.fillStyle = 'rgba(236,236,236,.7)'
  for (let i = 0; i < 256; i++) {
    const v = max ? Math.min(1, Math.sqrt(h.bins[i] / max)) : 0
    ctx.fillRect(i, 70 - v * 68, 1, v * 68)
  }
  if (h.hi > 0.002) {
    ctx.fillStyle = `rgb(${COLORS.danger})`
    ctx.fillRect(250, 0, 6, 70)
  }
  if (h.lo > 0.002) {
    ctx.fillStyle = `rgb(${COLORS.cold})`
    ctx.fillRect(0, 0, 6, 70)
  }
}
watch(() => props.histogram, draw)
onMounted(draw)
const pct = (v) => `${((v || 0) * 100).toFixed(1)}%`
</script>

<template>
  <div class="lv-hist" data-testid="lv-hist" role="img" aria-label="Luminance histogram">
    <canvas ref="cv" width="256" height="70" />
    <div class="flex justify-between font-mono text-[10.5px] font-medium tabular-nums">
      <span class="text-camera-cold" data-testid="lv-clip-shadow"
        >Shadows {{ pct(histogram?.lo) }}</span
      >
      <span class="text-camera-danger" data-testid="lv-clip-highlight"
        >Highlights {{ pct(histogram?.hi) }}</span
      >
    </div>
  </div>
</template>

<style scoped>
.lv-hist {
  display: grid;
  gap: 4px;
  width: 200px;
  padding: 8px 8px 6px;
  border-radius: 8px;
  background: rgba(21, 21, 21, 0.82);
  border: 1px solid theme('colors.camera.border');
  pointer-events: none;
}
.lv-hist canvas {
  width: 100%;
  height: 56px;
}
</style>
