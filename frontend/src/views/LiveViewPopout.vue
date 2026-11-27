<script setup>
/** The live view alone, in its own window (opened from Shoot with ?popout=liveview). */
import { onMounted } from 'vue'
import { useCameraStore } from '@/stores/camera'
import CameraGate from '@/components/shell/CameraGate.vue'
import LiveViewPanel from '@/components/shoot/LiveViewPanel.vue'

const camera = useCameraStore()
onMounted(() => {
  document.title = 'Live view'
})
</script>

<template>
  <main class="popout" data-test="liveview-popout">
    <h1 class="sr-only">Live view</h1>
    <LiveViewPanel v-if="camera.connected" popout />
    <div v-else class="gate" data-test="lv-gate"><CameraGate /></div>
  </main>
</template>

<style scoped>
.popout {
  height: 100dvh;
  padding: 8px;
  box-sizing: border-box;
  background: theme('colors.camera.bg');
  container-type: size;
  --lvh: 100cqh;
  display: grid;
  align-content: center;
}
.gate {
  display: grid;
  place-items: center;
  padding: 16px;
}
</style>
