<script setup>
/** Bottom-centre focus pill: large and small steps nearer and farther, Autofocus in the middle. */
import UiIcon from '@/components/ui/UiIcon.vue'

defineProps({ disabled: Boolean, busy: Boolean })
/** step(direction, size): direction -1 nearer / 1 farther; size 'small' | 'large' */
const emit = defineEmits(['step', 'autofocus'])
</script>

<template>
  <div class="lv-focus" role="toolbar" aria-label="Focus" data-testid="lv-focus">
    <button
      type="button"
      :disabled="disabled"
      aria-label="Large step nearer"
      title="Large step nearer"
      data-testid="lv-focus-near-large"
      @click="emit('step', -1, 'large')"
    >
      <UiIcon name="ChevronsLeft" :size="16" />
    </button>
    <button
      type="button"
      :disabled="disabled"
      aria-label="Small step nearer"
      title="Small step nearer"
      data-testid="lv-focus-near-small"
      @click="emit('step', -1, 'small')"
    >
      <UiIcon name="ChevronLeft" :size="16" />
    </button>
    <button
      type="button"
      class="af"
      :disabled="disabled || busy"
      title="Autofocus at the focus point"
      data-testid="lv-autofocus"
      @click="emit('autofocus')"
    >
      <UiIcon name="Crosshair" :size="16" />
      <span class="lbl">Autofocus</span>
    </button>
    <button
      type="button"
      :disabled="disabled"
      aria-label="Small step farther"
      title="Small step farther"
      data-testid="lv-focus-far-small"
      @click="emit('step', 1, 'small')"
    >
      <UiIcon name="ChevronRight" :size="16" />
    </button>
    <button
      type="button"
      :disabled="disabled"
      aria-label="Large step farther"
      title="Large step farther"
      data-testid="lv-focus-far-large"
      @click="emit('step', 1, 'large')"
    >
      <UiIcon name="ChevronsRight" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.lv-focus {
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
  border-radius: 9999px;
  border: 0;
  background: none;
  color: theme('colors.camera.muted');
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color 0.12s,
    color 0.12s;
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
html[data-layout='touch'] button {
  height: 44px;
  min-width: 44px;
}
/* The frame is a size container (see LiveViewPanel): icon-only Autofocus when narrow */
@container lv (max-width: 1100px) {
  .lbl {
    display: none;
  }
}
</style>
