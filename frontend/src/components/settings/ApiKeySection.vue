<script setup>
import { ref, computed } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiModal from '@/components/ui/UiModal.vue'

const config = useConfigStore()
const toasts = useToastsStore()

const isSet = computed(() => !!config.config?.api_key_set)
const busy = ref(false)
const newKey = ref('')
const copied = ref(false)

async function run(fn) {
  busy.value = true
  try {
    return await fn()
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = false
  }
}
const generate = () =>
  run(async () => {
    copied.value = false
    newKey.value = await config.createApiKey()
  })
const remove = () => run(() => config.deleteApiKey().then(() => toasts.success('API key removed')))

async function copy() {
  try {
    await navigator.clipboard.writeText(newKey.value)
    copied.value = true
  } catch {
    toasts.error('Copy failed. Select the key and copy it manually.')
  }
}
const saved = () => {
  newKey.value = ''
  copied.value = false
}
</script>

<template>
  <UiCard title="API key" subtitle="Protects the camera API on your network.">
    <template #actions>
      <UiBadge :tone="isSet ? 'ok' : 'warn'" data-test="key-status">
        {{ isSet ? 'Key set' : 'Not set' }}
      </UiBadge>
    </template>
    <div class="flex flex-col gap-3">
      <div class="flex flex-wrap gap-2">
        <UiConfirmButton
          v-if="isSet"
          confirm-text="Rotate key?"
          :loading="busy"
          data-test="rotate"
          @confirm="generate"
        >
          Rotate key
        </UiConfirmButton>
        <UiButton v-else variant="primary" :loading="busy" data-test="generate" @click="generate">
          Generate key
        </UiButton>
        <UiConfirmButton
          v-if="isSet"
          variant="danger"
          confirm-text="Remove key?"
          :disabled="busy"
          data-test="remove"
          @confirm="remove"
        >
          Remove key
        </UiConfirmButton>
      </div>
      <p class="text-xs text-camera-muted">
        Locked out? Delete <code>data/api_key.json</code> on the host and restart to remove the key.
      </p>
    </div>

    <UiModal :open="!!newKey" title="Your new API key" :closable="false">
      <p class="mb-2 text-sm">
        Copy this key now. It is shown only once and this browser is already signed in with it.
      </p>
      <code class="block break-all rounded bg-camera-bg p-3 text-sm" data-test="new-key">{{
        newKey
      }}</code>
      <template #footer>
        <UiButton data-test="copy" @click="copy">{{ copied ? 'Copied' : 'Copy' }}</UiButton>
        <UiButton variant="primary" data-test="saved" @click="saved">I've saved it</UiButton>
      </template>
    </UiModal>
  </UiCard>
</template>
