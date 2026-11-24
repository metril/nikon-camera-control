<script setup>
/** Status chip in the header. Connected: opens the camera popover. Otherwise: connects. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useEventsStore } from '@/stores/events'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import { leaseOwner } from '@/labels'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import StorageChip from './StorageChip.vue'
import { isNoPermission } from './connectError'
import { formatBytes } from './format'
import { useCameraStatus } from './useCameraStatus'

const emit = defineEmits(['shortcuts'])
const camera = useCameraStore()
const events = useEventsStore()
const storage = useStorageStore()
const toasts = useToastsStore()
const { status } = useCameraStatus()

const open = ref(false)
const root = ref(null)
const working = ref(false)

const SOCKET = {
  open: { tone: 'text-camera-ok', text: 'Live' },
  connecting: { tone: 'text-camera-muted', text: 'Connecting…' },
  closed: { tone: 'text-camera-warn', text: 'Offline' },
  unauthorized: { tone: 'text-camera-danger', text: 'Key needed' },
  forbidden: { tone: 'text-camera-danger', text: 'Origin not allowed' },
}
const socket = computed(() => SOCKET[events.status] || SOCKET.closed)
const battery = computed(() => {
  const b = camera.battery
  if (!b) return null
  if (typeof b.percent === 'number') return `${Math.round(b.percent)}%`
  return b.level != null ? String(b.level) : null
})
const cards = computed(() => camera.storage?.cards || [])
const shotsLeft = computed(() => cards.value.reduce((n, c) => n + (c.free_images || 0), 0))
const free = computed(() =>
  cards.value.length
    ? formatBytes(cards.value.reduce((n, c) => n + (c.free_kb || 0), 0) * 1024)
    : null,
)
const badgeTone = computed(() => ({ ok: 'ok', busy: 'warn', off: 'danger' })[status.value.dot])

async function connect() {
  working.value = true
  try {
    await camera.connect()
  } catch (e) {
    // a permission failure is explained on the Shoot tab, not as an error toast
    if (!isNoPermission(e)) toasts.error(e)
  } finally {
    working.value = false
  }
}
async function disconnect() {
  open.value = false
  working.value = true
  try {
    await camera.disconnect()
  } catch (e) {
    toasts.error(e)
  } finally {
    working.value = false
  }
}
function onChip() {
  if (camera.connected) open.value = !open.value
  else if (!working.value && camera.state !== 'connecting') connect()
}

function outside(e) {
  if (open.value && !root.value?.contains(e.target)) open.value = false
}
function onKey(e) {
  if (e.key === 'Escape' && open.value) {
    open.value = false
    root.value?.querySelector('[data-test="chip"]')?.focus()
  }
}
watch(open, (on) => {
  if (on) document.addEventListener('pointerdown', outside, true)
  else document.removeEventListener('pointerdown', outside, true)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside, true))
watch(
  () => camera.connected,
  (on) => !on && (open.value = false),
)
</script>

<template>
  <div ref="root" class="relative" @keydown="onKey">
    <button
      type="button"
      class="chip"
      data-test="chip"
      :aria-haspopup="camera.connected ? 'dialog' : undefined"
      :aria-expanded="camera.connected ? open : undefined"
      :aria-label="`Camera: ${status.label}`"
      @click="onChip"
    >
      <i class="dot" :class="status.dot" aria-hidden="true" />
      <span class="txt" data-test="state">{{ status.label }}</span>
    </button>

    <div v-if="open" class="pop" role="dialog" aria-label="Camera" data-test="camera-popover">
      <div class="flex items-center justify-between gap-3">
        <b class="min-w-0 truncate" data-test="model">{{ camera.model || 'Camera' }}</b>
        <UiBadge :tone="badgeTone">{{ status.label }}</UiBadge>
      </div>
      <dl class="kv">
        <template v-if="camera.serial">
          <dt>Serial number</dt>
          <dd class="tabular-nums">{{ camera.serial }}</dd>
        </template>
        <template v-if="camera.leasedBy">
          <dt>Busy with</dt>
          <dd data-test="lease">{{ leaseOwner(camera.leasedBy) }}</dd>
        </template>
        <dt>Battery</dt>
        <dd class="tabular-nums" data-test="battery">{{ battery || '–' }}</dd>
        <dt>Card</dt>
        <dd class="tabular-nums" data-test="storage">
          <template v-if="cards.length"
            >{{ shotsLeft.toLocaleString('en-GB') }} shots left · {{ free }}</template
          >
          <template v-else>–</template>
        </dd>
        <template v-if="storage.loaded">
          <dt>Saves to</dt>
          <dd><StorageChip /></dd>
        </template>
        <dt>Live updates</dt>
        <dd :class="socket.tone" data-test="socket">{{ socket.text }}</dd>
      </dl>
      <UiButton class="w-full" :loading="working" data-test="toggle" @click="disconnect">
        Disconnect
      </UiButton>
      <UiButton
        variant="ghost"
        size="sm"
        class="shortcuts w-full"
        @click="((open = false), emit('shortcuts'))"
      >
        <UiIcon name="Keyboard" :size="16" /> Keyboard shortcuts
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
.chip {
  height: var(--ctl-sm);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border-radius: 9999px;
  border: 1px solid theme('colors.camera.border');
  background: theme('colors.camera.raised');
  font-weight: 500;
  font-size: 13px;
  white-space: nowrap;
  cursor: pointer;
}
.chip:hover,
.chip:active {
  background: theme('colors.camera.hover');
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
  background: theme('colors.camera.ok');
}
.dot.off {
  background: theme('colors.camera.danger');
}
.dot.busy {
  background: theme('colors.camera.warn');
}
.pop {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 41;
  width: 280px;
  max-width: calc(100vw - 16px);
  display: grid;
  gap: 12px;
  padding: 16px;
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.card');
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.55);
}
.kv {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 12px;
  font-size: 13px;
  margin: 0;
}
.kv dt {
  color: theme('colors.camera.muted');
}
.kv dd {
  margin: 0;
  font-weight: 500;
  text-align: right;
  min-width: 0;
}
:global(html[data-layout='touch']) .shortcuts {
  display: none;
}
@media (max-width: 560px) {
  .txt {
    display: none;
  }
}
</style>
