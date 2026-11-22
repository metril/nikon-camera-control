<script setup>
import { computed, ref, watch } from 'vue'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import AdvCard from './AdvCard.vue'
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
  <AdvCard title="Camera clock and storage" subtitle="Clock sync and capture target">
    <template #default="{ disabled, reason }">
      <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm" data-testid="clock">
        <dt class="text-slate-400">Camera</dt>
        <dd>{{ view?.camera ?? '–' }}</dd>
        <dt class="text-slate-400">This device</dt>
        <dd>{{ view?.device ?? '–' }}</dd>
        <dt class="text-slate-400">Offset</dt>
        <dd data-testid="offset">{{ view ? diffText : '–' }}</dd>
      </dl>
      <div class="flex flex-wrap gap-2">
        <UiButton :loading="loadingClock" @click="loadClock">Refresh</UiButton>
        <UiButton
          variant="primary"
          :loading="syncing"
          :disabled="disabled || recordingNow"
          :title="reason"
          @click="sync"
        >
          Sync camera clock to this device
        </UiButton>
      </div>

      <div class="space-y-1 border-t border-slate-700 pt-3">
        <UiSelect
          :model-value="target?.value"
          label="Capture target"
          :options="targetOptions"
          :disabled="disabled || recordingNow || savingTarget || !targetOptions.length"
          @update:model-value="setTarget"
        />
        <p v-if="reason || recordingNow" class="text-xs text-slate-400" data-testid="target-reason">
          {{ reason || 'Not while recording' }}
        </p>
      </div>
    </template>
  </AdvCard>
</template>
