<script setup>
/** Top-left pill of live view tools (icon + label); scrolls horizontally when narrow.
 * `compact` (touch portrait / narrow): two tools inline, the rest under a More button. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { useKeyboardHints } from '@/composables/useKeyboardHints'
import { useLiveViewStore } from '@/stores/liveview'
import { useToastsStore } from '@/stores/toasts'

const props = defineProps({ compact: Boolean })
const lv = useLiveViewStore()
const toasts = useToastsStore()
const { hints } = useKeyboardHints()
const KEYS = { grid: '3', hist: 'H', clip: 'C', peak: 'P', loupe: 'L', onion: 'O' }
const tip = (key, text) => (hints.value && KEYS[key] ? `${text} (${KEYS[key]})` : text)
const GRID_LABEL = { thirds: 'Thirds', golden: 'Golden', centre: 'Centre', off: 'Grid off' }

const items = computed(() => [
  {
    key: 'grid',
    icon: 'Grid3x3',
    label: GRID_LABEL[lv.tools.grid] || 'Thirds',
    pressed: lv.tools.grid !== 'off',
    title: tip('grid', 'Grid: press to cycle thirds, golden, centre, off'),
    aria: `Grid: ${GRID_LABEL[lv.tools.grid] || 'Thirds'}. Press to change`,
    click: () => {
      lv.cycleGrid()
      toasts.info(`Grid: ${GRID_LABEL[lv.tools.grid] || 'Thirds'}`, 1500)
    },
  },
  { key: 'hist', icon: 'ChartColumn', label: 'Histogram' },
  { key: 'clip', icon: 'Sun', label: 'Clipping' },
  { key: 'peak', icon: 'Sparkles', label: 'Peaking' },
  { key: 'loupe', icon: 'ZoomIn', label: 'Loupe' },
  { key: 'onion', icon: 'Layers', label: 'Last shot overlay' },
])

const INLINE = 2
const inline = computed(() => (props.compact ? items.value.slice(0, INLINE) : items.value))
const rest = computed(() => (props.compact ? items.value.slice(INLINE) : []))
const moreOpen = ref(false)
const anyOn = computed(() => rest.value.some((t) => t.pressed ?? lv.tools[t.key]))
const run = (t) => (t.click ? t.click() : lv.toggleTool(t.key))

// A fade at the right edge shows there is more to scroll to
const bar = ref(null)
const more = ref(false)
function measure() {
  const el = bar.value
  more.value = !!el && el.scrollLeft + el.clientWidth < el.scrollWidth - 2
}
let ro = null
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && bar.value) {
    ro = new ResizeObserver(measure)
    ro.observe(bar.value)
  }
})
onBeforeUnmount(() => ro?.disconnect())
</script>

<template>
  <div class="lv-tools" @keydown.esc="moreOpen = false">
    <div
      ref="bar"
      class="lv-toolbar"
      :class="{ more: more && !compact, wrap: compact }"
      role="toolbar"
      aria-label="Live view tools"
      data-testid="lv-toolbar"
      @scroll.passive="measure"
    >
      <button
        v-for="t in inline"
        :key="t.key"
        type="button"
        :data-testid="`lv-tool-${t.key}`"
        :aria-pressed="t.pressed ?? lv.tools[t.key]"
        :title="t.title || tip(t.key, t.label)"
        :aria-label="t.aria || t.label"
        @click="run(t)"
      >
        <UiIcon :name="t.icon" :size="16" />
        <span>{{ t.label }}</span>
      </button>
      <button
        v-if="compact"
        type="button"
        class="more-btn"
        :class="{ on: anyOn }"
        data-testid="lv-more"
        aria-haspopup="true"
        :aria-expanded="moreOpen"
        @click="moreOpen = !moreOpen"
      >
        <UiIcon name="SlidersHorizontal" :size="16" />
        <span>More</span>
      </button>
    </div>
    <div
      v-if="compact && moreOpen"
      class="lv-morepop"
      role="group"
      aria-label="More live view tools"
    >
      <button
        v-for="t in rest"
        :key="t.key"
        type="button"
        :data-testid="`lv-tool-${t.key}`"
        :aria-pressed="t.pressed ?? lv.tools[t.key]"
        :title="t.title || tip(t.key, t.label)"
        :aria-label="t.aria || t.label"
        @click="run(t)"
      >
        <UiIcon :name="t.icon" :size="16" />
        <span>{{ t.label }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.lv-tools {
  display: grid;
  gap: 6px;
  min-width: 0;
  justify-items: start;
}
.lv-morepop {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  max-width: 100%;
  padding: 3px;
  border-radius: 22px;
  background: theme('colors.camera.overlay');
  border: 1px solid theme('colors.camera.border');
}
.more-btn.on::after {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: theme('colors.camera.accent');
}
.lv-toolbar {
  display: flex;
  gap: 2px;
  padding: 3px;
  min-width: 0;
  border-radius: 9999px;
  background: theme('colors.camera.overlay');
  border: 1px solid theme('colors.camera.border');
  backdrop-filter: blur(6px);
  overflow-x: auto;
  scrollbar-width: none;
}
.lv-toolbar.wrap {
  flex-wrap: wrap;
  overflow: visible;
  border-radius: 24px;
  max-width: 100%;
}
.lv-toolbar.more {
  -webkit-mask-image: linear-gradient(90deg, #000 85%, transparent);
  mask-image: linear-gradient(90deg, #000 85%, transparent);
}
.lv-toolbar::-webkit-scrollbar {
  display: none;
}
button {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 6px;
  height: var(--ctl-sm);
  padding: 0 10px;
  border-radius: 9999px;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 500;
  color: theme('colors.camera.muted');
  background: none;
  border: 0;
  cursor: pointer;
  transition:
    background-color 0.12s,
    color 0.12s;
}
button:hover {
  color: theme('colors.camera.text');
}
button:active:not([aria-pressed='true']) {
  background: rgba(255, 255, 255, 0.12);
  color: theme('colors.camera.text');
}
button[aria-pressed='true'] {
  background: theme('colors.camera.text');
  color: theme('colors.camera.bg');
}
html[data-layout='touch'] button {
  height: 44px;
  padding: 0 14px;
}
html[data-layout='touch'] .lv-toolbar,
html[data-layout='touch'] .lv-morepop {
  gap: 4px;
}
/* Touch: icon-only once the frame is too narrow for the labels (the labels stay as accessible names) */
@container lv (max-width: 840px) {
  html[data-layout='touch'] .lv-toolbar:not(.wrap) button span {
    display: none;
  }
  html[data-layout='touch'] .lv-toolbar:not(.wrap) button {
    padding: 0;
    width: 44px;
    justify-content: center;
  }
}
html[data-layout='touch'] button {
  font-size: var(--fs-min);
}
</style>
