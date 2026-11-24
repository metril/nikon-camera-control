<script setup>
import { computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { formatBytes } from '@/components/shell/format'
import { cameraBackend } from '@/labels'

const auth = useAuthStore()
const info = computed(() => auth.info)
onMounted(() => auth.fetchInfo().catch(() => {}))
</script>

<template>
  <UiCard title="About">
    <dl
      v-if="info"
      class="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-6 gap-y-2 text-sm"
    >
      <dt class="text-camera-muted">Version</dt>
      <dd class="tabular-nums" data-test="version">{{ info.version }}</dd>
      <dt class="text-camera-muted">Camera backend</dt>
      <dd>
        <UiBadge :tone="info.backend === 'demo' ? 'warn' : 'ok'" data-test="backend">{{
          cameraBackend(info.backend)
        }}</UiBadge>
      </dd>
      <template v-if="info.libgphoto2_version">
        <dt class="text-camera-muted">libgphoto2</dt>
        <dd class="tabular-nums" data-test="libgphoto2">{{ info.libgphoto2_version }}</dd>
      </template>
      <dt class="text-camera-muted">ffmpeg</dt>
      <dd>
        <UiBadge :tone="info.ffmpeg_available ? 'ok' : 'warn'" data-test="ffmpeg">
          {{ info.ffmpeg_available ? 'Available' : 'Not found' }}
        </UiBadge>
      </dd>
      <dt class="text-camera-muted">Output disk free</dt>
      <dd class="tabular-nums" data-test="disk">{{ formatBytes(info.output_free_bytes) }}</dd>
      <dt class="text-camera-muted">API docs</dt>
      <dd>
        <a href="/docs" target="_blank" rel="noopener" class="text-camera-accent underline"
          >Open the API docs</a
        >
      </dd>
    </dl>
    <p v-else class="text-sm text-camera-muted">Server info unavailable.</p>
  </UiCard>
</template>
