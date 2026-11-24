<script setup>
/** Bottom-centre focus pill: large and small steps nearer and farther, Autofocus in the middle. */
import { ref, watch } from 'vue'
import UiIcon from '@/components/ui/UiIcon.vue'

const props = defineProps({
  disabled: Boolean,
  busy: Boolean,
  mode: { type: String, default: 'af' },
  /** Direction at the lens focus limit: -1 closest, 1 farthest, 0 none. */
  limit: { type: Number, default: 0 },
  /** Changes on every rejected step at a limit: replays the edge bump. */
  bump: { type: Number, default: 0 },
})
const bumping = ref(0) // side of the pill nudging: -1 left, 1 right
let bumpTimer
watch(
  () => props.bump,
  () => {
    if (!props.limit) return
    clearTimeout(bumpTimer)
    bumping.value = 0
    requestAnimationFrame(() => {
      bumping.value = props.limit
      bumpTimer = setTimeout(() => (bumping.value = 0), 220)
    })
  },
)
const LIMIT_TITLE = { '-1': 'Closest focus', 1: 'Farthest focus' }
/** step(direction, size): direction -1 nearer / 1 farther; size 'small' | 'large' */
const emit = defineEmits(['step', 'autofocus', 'mode'])
</script>

<template>
  <div
    class="lv-focus"
    :class="{ 'bump-near': bumping === -1, 'bump-far': bumping === 1 }"
    role="toolbar"
    aria-label="Focus"
    data-testid="lv-focus"
  >
    <button
      type="button"
      :disabled="disabled"
      :aria-disabled="limit === -1 || undefined"
      :class="{ limited: limit === -1 }"
      aria-label="Large step nearer"
      :title="limit === -1 ? LIMIT_TITLE[-1] : 'Large step nearer'"
      data-testid="lv-focus-near-large"
      @click="emit('step', -1, 'large')"
    >
      <UiIcon name="ChevronsLeft" :size="16" />
    </button>
    <button
      type="button"
      :disabled="disabled"
      :aria-disabled="limit === -1 || undefined"
      :class="{ limited: limit === -1 }"
      aria-label="Small step nearer"
      :title="limit === -1 ? LIMIT_TITLE[-1] : 'Small step nearer'"
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
      {{ mode === 'manual' ? 'Manual' : 'Auto' }}
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
      :aria-disabled="limit === 1 || undefined"
      :class="{ limited: limit === 1 }"
      aria-label="Small step farther"
      :title="limit === 1 ? LIMIT_TITLE[1] : 'Small step farther'"
      data-testid="lv-focus-far-small"
      @click="emit('step', 1, 'small')"
    >
      <UiIcon name="ChevronRight" :size="16" />
    </button>
    <button
      type="button"
      :disabled="disabled"
      :aria-disabled="limit === 1 || undefined"
      :class="{ limited: limit === 1 }"
      aria-label="Large step farther"
      :title="limit === 1 ? LIMIT_TITLE[1] : 'Large step farther'"
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
button.limited {
  opacity: 0.4;
  cursor: not-allowed;
}
button.limited:hover {
  background: none;
  color: theme('colors.camera.muted');
}
.bump-near {
  animation: lv-bump-near 0.2s ease-out;
}
.bump-far {
  animation: lv-bump-far 0.2s ease-out;
}
@keyframes lv-bump-near {
  40% {
    transform: translateX(-4px);
    border-left-color: theme('colors.camera.text');
  }
}
@keyframes lv-bump-far {
  40% {
    transform: translateX(4px);
    border-right-color: theme('colors.camera.text');
  }
}
@media (prefers-reduced-motion: reduce) {
  .bump-near,
  .bump-far {
    animation-name: lv-bump-flash;
  }
  @keyframes lv-bump-flash {
    40% {
      border-color: theme('colors.camera.text');
    }
  }
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
@container lv (max-width: 720px) {
  .lbl {
    display: none;
  }
}
</style>
