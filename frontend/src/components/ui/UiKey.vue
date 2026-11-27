<script setup>
/** One on-screen key (56px on touch). Shared by UiKeypad and any later keyboard. */
defineProps({
  /** default | accent | quiet */
  variant: { type: String, default: 'default' },
  disabled: Boolean,
})
</script>

<template>
  <button type="button" class="ukey" :class="variant" :disabled="disabled">
    <slot />
  </button>
</template>

<style scoped>
.ukey {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 56px;
  height: 56px;
  padding: 0 8px;
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.control');
  background: theme('colors.camera.raised');
  color: theme('colors.camera.text');
  font:
    500 20px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  cursor: pointer;
  transition: background-color 0.12s;
}
.ukey:active:not(:disabled) {
  background: theme('colors.camera.hover');
}
.ukey:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ukey.quiet {
  background: none;
  color: theme('colors.camera.muted');
}
.ukey.accent {
  background: theme('colors.camera.accent');
  border-color: theme('colors.camera.accent');
  color: theme('colors.camera.accent-ink');
  font-family: system-ui, sans-serif;
  font-weight: 600;
}
.ukey.accent:active:not(:disabled) {
  background: theme('colors.camera.accent-hover');
}
</style>
