<script setup>
/** A bordered grid of label/value cells. `items`: [{ key, label, value, note?, testid? }] */
defineProps({
  items: { type: Array, required: true },
  /** Column count above 640px. */
  cols: { type: Number, default: 3 },
  /** Column count on phones (defaults to `cols`). */
  compactCols: { type: Number, default: 0 },
})
</script>

<template>
  <dl
    class="stat-grid m-0 grid gap-px overflow-hidden rounded-inner border border-camera-subtle bg-camera-subtle"
    :style="{ '--cols': cols, '--compact': compactCols || cols }"
  >
    <div
      v-for="it in items"
      :key="it.key || it.label"
      class="grid min-w-0 gap-0.5 bg-camera-surface px-3 py-2.5"
    >
      <dt class="text-xs text-camera-muted">{{ it.label }}</dt>
      <dd
        class="m-0 truncate font-mono text-[15px] font-medium tabular-nums"
        :data-test="it.testid"
      >
        {{ it.value }}
        <small v-if="it.note" class="font-sans text-xs font-normal text-camera-warn">{{
          it.note
        }}</small>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.stat-grid {
  grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
}
@media (max-width: 640px) {
  .stat-grid {
    grid-template-columns: repeat(var(--compact), minmax(0, 1fr));
  }
}
</style>
