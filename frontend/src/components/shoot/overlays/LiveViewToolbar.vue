<script setup>
/** Top-left pill of live view tools (icon + label); scrolls horizontally when narrow. */
import { computed } from 'vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { useLiveViewStore } from '@/stores/liveview'

const lv = useLiveViewStore()
const GRID_LABEL = { thirds: 'Thirds', golden: 'Golden', centre: 'Centre', off: 'Grid off' }

const items = computed(() => [
  {
    key: 'grid',
    icon: 'Grid3x3',
    label: GRID_LABEL[lv.tools.grid] || 'Thirds',
    pressed: lv.tools.grid !== 'off',
    title: 'Grid: click to cycle thirds, golden, centre, off',
    click: () => lv.cycleGrid(),
  },
  { key: 'hist', icon: 'ChartColumn', label: 'Histogram' },
  { key: 'clip', icon: 'Sun', label: 'Clipping' },
  { key: 'peak', icon: 'Sparkles', label: 'Peaking' },
  { key: 'loupe', icon: 'ZoomIn', label: 'Loupe' },
  { key: 'onion', icon: 'Layers', label: 'Last shot overlay' },
])
</script>

<template>
  <div class="lv-toolbar" role="toolbar" aria-label="Live view tools" data-testid="lv-toolbar">
    <button
      v-for="t in items"
      :key="t.key"
      type="button"
      :data-testid="`lv-tool-${t.key}`"
      :aria-pressed="t.pressed ?? lv.tools[t.key]"
      :title="t.title || t.label"
      @click="t.click ? t.click() : lv.toggleTool(t.key)"
    >
      <UiIcon :name="t.icon" :size="16" />
      <span>{{ t.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.lv-toolbar {
  display: flex;
  gap: 2px;
  padding: 3px;
  min-width: 0;
  border-radius: 9999px;
  background: rgba(21, 21, 21, 0.82);
  border: 1px solid theme('colors.camera.border');
  backdrop-filter: blur(6px);
  overflow-x: auto;
  scrollbar-width: none;
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
</style>
