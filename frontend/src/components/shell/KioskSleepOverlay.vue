<script setup>
import { useKioskSleep } from '@/composables/useKioskSleep'

// Kiosk only (page URL has kiosk=1): a black cover shown while the screen sleeps.
const { asleep, onOverlayDown, swallow } = useKioskSleep()
</script>

<template>
  <div
    v-if="asleep"
    class="sleep"
    data-test="kiosk-sleep"
    aria-hidden="true"
    @pointerdown="onOverlayDown"
    @keydown="swallow"
    @click="swallow"
    @touchstart.prevent
    @contextmenu.prevent
  />
</template>

<style scoped>
.sleep {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: #000;
  cursor: none;
  touch-action: none;
}
</style>
