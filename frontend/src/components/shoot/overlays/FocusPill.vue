<script setup>
/** Bottom-centre focus pill: large and small steps nearer and farther, Autofocus in the middle. */
import UiIcon from '@/components/ui/UiIcon.vue'

defineProps({
  disabled: Boolean,
  busy: Boolean,
  mode: { type: String, default: 'af' },
})
/** step(direction, size): direction -1 nearer / 1 farther; size 'small' | 'large' */
const emit = defineEmits(['step', 'autofocus', 'mode'])
</script>

<template>
  <div class="lv-focus" role="toolbar" aria-label="Focus" data-testid="lv-focus">
    <button
      type="button"
      :disabled="disabled"
      aria-label="Large step nearer"
      title="Large step nearer"
      class="step s1"
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
      class="step s2"
      data-testid="lv-focus-near-small"
      @click="emit('step', -1, 'small')"
    >
      <UiIcon name="ChevronLeft" :size="16" />
    </button>
    <button
      type="button"
      class="mode"
      :aria-pressed="mode === 'manual'"
      :aria-label="
        mode === 'manual' ? 'Manual focus: tap moves the AF point only' : 'Autofocus: tap focuses'
      "
      :title="
        mode === 'manual'
          ? 'Manual: tapping only moves the AF point'
          : 'Autofocus: tapping runs autofocus'
      "
      data-testid="lv-focus-mode"
      @click="emit('mode', mode === 'manual' ? 'af' : 'manual')"
    >
      <span class="pre">Focus: </span>{{ mode === 'manual' ? 'Manual' : 'Auto' }}
    </button>
    <button
      v-if="mode !== 'manual'"
      type="button"
      class="af"
      aria-label="Autofocus"
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
      class="step s3"
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
      class="step s4"
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
  background: theme('colors.camera.overlay');
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
/* Touch: the pill sits outside the image, in a narrow rail on landscape screens */
html[data-layout='touch'] .lv-focus {
  flex-wrap: wrap;
  justify-content: center;
  border-radius: 24px;
  max-width: 100%;
}
@media (max-width: 480px) {
  html[data-layout='touch'] .lbl {
    display: none;
  }
}
/* The frame is a size container (see LiveViewPanel): icon-only Autofocus when narrow */
/* Landscape rail: « ‹ › » on one line, Autofocus under it, the AF mode last */
@media (min-width: 900px) and (orientation: landscape) {
  html[data-layout='touch'] .lv-focus {
    display: grid;
    grid-template-columns: repeat(4, 44px);
    justify-content: center;
    gap: 6px 0;
    padding: 0;
    border: 0;
    background: none;
    backdrop-filter: none;
  }
  html[data-layout='touch'] .lv-focus .lbl {
    display: inline;
  }
  html[data-layout='touch'] .lv-focus .pre {
    display: inline;
  }
  html[data-layout='touch'] .lv-focus .s1 {
    order: 1;
  }
  html[data-layout='touch'] .lv-focus .s2 {
    order: 2;
  }
  html[data-layout='touch'] .lv-focus .s3 {
    order: 3;
  }
  html[data-layout='touch'] .lv-focus .s4 {
    order: 4;
  }
  html[data-layout='touch'] .lv-focus .af {
    order: 5;
    grid-column: 1 / -1;
    margin: 0;
  }
  html[data-layout='touch'] .lv-focus .mode {
    order: 6;
    grid-column: 1 / -1;
    border: 1px solid theme('colors.camera.border');
  }
}
.pre {
  display: none;
}
@container lv (max-width: 720px) {
  .lbl {
    display: none;
  }
}
</style>
