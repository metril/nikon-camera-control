<script setup>
import { computed, ref, watch } from 'vue'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import { leaseOwner } from '@/labels'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'

const camera = useCameraStore()
const toasts = useToastsStore()

const admin = useCameraAdminStore()
const clock = computed(() => admin.clock)
const target = computed(() => admin.target)
const syncing = ref(false)
const loadingClock = ref(false)
const savingTarget = ref(false)

const TZ = /(Z|[+-]\d\d:?\d\d)$/i
const fmt = (ms) => new Date(ms).toISOString().replace('T', ' ').slice(0, 19)
const browserOffset = () => -new Date().getTimezoneOffset()

/** Camera wall clock vs this device's wall clock, both as "naive" instants, in seconds. */
const view = computed(() => {
  if (!clock.value) return null
  const { data, fetchedAt } = clock.value
  const raw = String(data.camera_wall_time ?? data.camera_time)
  const cam = Date.parse(TZ.test(raw) ? raw : `${raw}Z`)
  const dev = fetchedAt + browserOffset() * 60000
  const diff = Math.round((cam - dev) / 1000)
  return { camera: fmt(cam), device: fmt(dev), diff }
})
const diffText = computed(() => {
  const d = view.value?.diff
  if (d === undefined) return ''
  if (Math.abs(d) < 2) return 'in sync'
  const a = Math.abs(d)
  const txt =
    a >= 3600 ? `${(a / 3600).toFixed(1)} h` : a >= 60 ? `${Math.round(a / 60)} min` : `${a} s`
  return `${txt} ${d > 0 ? 'ahead of' : 'behind'} this device`
})

const recordingNow = computed(() => camera.state === 'recording')
const reason = computed(() => {
  if (!camera.connected) return 'Camera not connected'
  if (camera.leasedBy) return `Busy: ${leaseOwner(camera.leasedBy)}`
  return ''
})
const disabled = computed(() => !!reason.value)
const targetOptions = computed(() =>
  (target.value?.choices || []).map((c) => ({ value: c, label: c })),
)

async function loadClock() {
  loadingClock.value = true
  try {
    await admin.fetchClock()
  } catch (e) {
    toasts.error(e)
  } finally {
    loadingClock.value = false
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
async function setTarget(value) {
  if (!value || value === target.value?.value) return
  savingTarget.value = true
  try {
    await admin.setTarget(value)
  } catch (e) {
    toasts.error(e)
    admin.fetchTarget().catch(() => {})
  } finally {
    savingTarget.value = false
  }
}

// Loaded on camera connect by the events store; load here when the card opens with nothing yet.
watch(
  () => camera.connected,
  (on) => {
    if (on && !admin.clock) admin.refresh()
  },
  { immediate: true },
)
</script>

<template>
  <UiCard title="Camera clock and storage" subtitle="Clock sync and where the camera saves photos">
    <div class="flex flex-col gap-4">
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm" data-testid="clock">
        <dt class="text-camera-muted">Camera</dt>
        <dd class="tabular-nums">{{ view?.camera ?? '–' }}</dd>
        <dt class="text-camera-muted">This device</dt>
        <dd class="tabular-nums">{{ view?.device ?? '–' }}</dd>
        <dt class="text-camera-muted">Offset</dt>
        <dd data-testid="offset">{{ view ? diffText : '–' }}</dd>
      </dl>
      <div class="flex flex-wrap gap-2">
        <UiButton :loading="loadingClock" @click="loadClock">Refresh</UiButton>
        <UiButton
          variant="primary"
          :loading="syncing"
          :disabled="disabled || recordingNow"
          @click="sync"
        >
          Sync camera clock to this device
        </UiButton>
      </div>
      <div class="flex flex-col gap-2 border-t border-camera-subtle pt-4">
        <UiSelect
          :model-value="target?.value"
          label="Camera saves to"
          :options="targetOptions"
          :disabled="disabled || recordingNow || savingTarget || !targetOptions.length"
          @update:model-value="setTarget"
        />
        <p v-if="reason || recordingNow" class="text-xs text-camera-muted" data-testid="target-reason">
          {{ reason || 'Not while recording' }}
        </p>
      </div>
    </div>
  </UiCard>
</template>
