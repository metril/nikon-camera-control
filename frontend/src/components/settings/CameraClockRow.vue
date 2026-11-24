<script setup>
import { computed, ref, watch } from 'vue'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import UiButton from '@/components/ui/UiButton.vue'
import SettingRow from './SettingRow.vue'

const camera = useCameraStore()
const admin = useCameraAdminStore()
const toasts = useToastsStore()
const syncing = ref(false)
const loading = ref(false)

const TZ = /(Z|[+-]\d\d:?\d\d)$/i
const fmt = (ms) => new Date(ms).toISOString().replace('T', ' ').slice(0, 19)
const browserOffset = () => -new Date().getTimezoneOffset()

/** Camera wall clock vs this device's wall clock, both as "naive" instants, in seconds. */
const view = computed(() => {
  if (!admin.clock) return null
  const { data, fetchedAt } = admin.clock
  const raw = String(data.camera_wall_time ?? data.camera_time)
  const cam = Date.parse(TZ.test(raw) ? raw : `${raw}Z`)
  const dev = fetchedAt + browserOffset() * 60000
  return { camera: fmt(cam), diff: Math.round((cam - dev) / 1000) }
})
const summary = computed(() => {
  if (!view.value) return 'Not read yet.'
  const d = view.value.diff
  let off = 'In sync with this device'
  if (Math.abs(d) >= 2) {
    const a = Math.abs(d)
    const txt =
      a >= 3600 ? `${(a / 3600).toFixed(1)} h` : a >= 60 ? `${Math.round(a / 60)} min` : `${a} s`
    off = `${txt} ${d > 0 ? 'ahead of' : 'behind'} this device`
  }
  return `${view.value.camera}. ${off}.`
})
const reason = computed(() => {
  if (!camera.connected) return 'Connect the camera to read its clock.'
  if (camera.state === 'recording') return 'Not while recording.'
  if (camera.leasedBy) return 'Not while the camera is busy.'
  return ''
})

async function refresh() {
  loading.value = true
  try {
    await admin.fetchClock()
  } catch (e) {
    toasts.error(e)
  } finally {
    loading.value = false
  }
}
async function sync() {
  syncing.value = true
  try {
    await admin.syncClock()
    toasts.success('Camera clock synced')
  } catch (e) {
    toasts.error(e)
  } finally {
    syncing.value = false
  }
}
watch(
  () => camera.connected,
  (on) => {
    if (on && !admin.clock) admin.refresh()
  },
  { immediate: true },
)
</script>

<template>
  <SettingRow title="Camera clock" data-field="camera-clock" natural>
    <template #note>
      <span data-test="clock-summary" class="tabular-nums">{{ summary }}</span>
      <span v-if="reason" class="block" data-test="clock-reason">{{ reason }}</span>
    </template>
    <div class="flex w-full flex-wrap gap-2">
      <UiButton
        size="sm"
        :loading="loading"
        :disabled="!!reason"
        data-test="clock-refresh"
        @click="refresh"
      >
        Refresh
      </UiButton>
      <UiButton
        size="sm"
        variant="primary"
        :loading="syncing"
        :disabled="!!reason"
        data-test="clock-sync"
        @click="sync"
      >
        Sync to this device
      </UiButton>
    </div>
  </SettingRow>
</template>
