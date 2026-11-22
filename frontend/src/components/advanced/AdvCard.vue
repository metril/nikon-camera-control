<script setup>
/** Card shell: empty state when disconnected, "Busy: <feature>" when another feature holds the camera. */
import { computed, ref } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import UiCard from '@/components/ui/UiCard.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiButton from '@/components/ui/UiButton.vue'

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  /** Lease name of the feature this card controls; its own lease never blocks it. */
  feature: { type: String, default: null },
})

const NAMES = { timelapse: 'time-lapse' }
const camera = useCameraStore()
const toasts = useToastsStore()
const connecting = ref(false)

const reason = computed(() => {
  if (!camera.connected) return 'Camera not connected'
  const by = camera.leasedBy
  if (by && by !== props.feature) return `Busy: ${NAMES[by] || by}`
  return ''
})

async function connect() {
  connecting.value = true
  try {
    await camera.connect()
  } catch (e) {
    toasts.error(e)
  } finally {
    connecting.value = false
  }
}
</script>

<template>
  <UiCard :title="title" :subtitle="subtitle">
    <template #actions><slot name="actions" /></template>
    <UiEmpty
      v-if="!camera.connected"
      title="Camera not connected"
      hint="Connect the camera to use this card."
    >
      <template #actions>
        <UiButton variant="primary" :loading="connecting" @click="connect">Connect</UiButton>
      </template>
    </UiEmpty>
    <div v-else class="space-y-3">
      <p
        v-if="reason"
        class="text-sm text-amber-300"
        role="status"
        aria-live="polite"
        data-testid="busy"
      >
        {{ reason }}
      </p>
      <slot :disabled="!!reason" :reason="reason" />
    </div>
  </UiCard>
</template>
