<script setup>
/**
 * The one "camera not connected" state of a view: Connect, a connecting spinner, or, when the
 * camera was found but cannot be opened, the udev fix. Views show this instead of their content.
 */
import { computed, ref } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { UDEV_COMMANDS, isNoPermission } from './connectError'

defineProps({ hint: { type: String, default: '' } })

const camera = useCameraStore()
const toasts = useToastsStore()
const busy = ref(false)

const connecting = computed(() => busy.value || camera.state === 'connecting')
const noPermission = computed(() => !camera.connected && isNoPermission(camera.lastError))

async function connect() {
  busy.value = true
  try {
    await camera.connect()
  } catch (e) {
    // a permission failure is explained right here, not as an error toast
    if (!isNoPermission(e)) toasts.error(e)
  } finally {
    busy.value = false
  }
}
async function copy() {
  try {
    await navigator.clipboard.writeText(UDEV_COMMANDS)
    toasts.success('Commands copied')
  } catch {
    toasts.warn('Could not copy. Select the commands and copy them by hand.')
  }
}
</script>

<template>
  <div class="mx-auto flex w-full max-w-[520px] flex-col gap-4" data-test="camera-gate">
    <template v-if="noPermission">
      <UiAlert tone="danger" title="Camera found, but the app can't open it">
        The camera is on USB, but its device file belongs to root, so the app isn't allowed to use
        it. Install the Nikon udev rule on the host, then unplug and replug the camera.
      </UiAlert>
      <pre
        class="m-0 overflow-x-auto whitespace-pre rounded-control border border-camera-subtle bg-camera-bg px-3 py-2.5 font-mono text-xs leading-relaxed text-camera-text"
        data-test="udev-commands"
        >{{ UDEV_COMMANDS }}</pre
      >
      <div class="flex flex-wrap gap-2">
        <UiButton variant="primary" :loading="connecting" @click="connect">Try again</UiButton>
        <UiButton @click="copy"><UiIcon name="Copy" :size="16" /> Copy commands</UiButton>
      </div>
    </template>
    <div v-else class="flex flex-col items-center gap-2.5 px-4 py-8 text-center text-camera-muted">
      <UiIcon name="Usb" :size="28" />
      <b class="text-[15px] text-camera-text">{{
        connecting ? 'Connecting…' : 'Camera not connected'
      }}</b>
      <span>{{
        connecting
          ? 'Looking for the camera on USB.'
          : hint || 'Plug the camera in over USB, switch it on and set the mode dial to P, A, S or M.'
      }}</span>
      <UiButton v-if="!connecting" variant="primary" data-test="gate-connect" @click="connect"
        >Connect</UiButton
      >
    </div>
  </div>
</template>
