<script setup>
import { ref } from 'vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useEventsStore } from '@/stores/events'
import UiModal from '@/components/ui/UiModal.vue'
import UiText from '@/components/ui/UiText.vue'
import UiButton from '@/components/ui/UiButton.vue'

const auth = useAuthStore()
const events = useEventsStore()
const key = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  const candidate = key.value.trim()
  if (!candidate || loading.value) return
  loading.value = true
  error.value = ''
  const previous = auth.apiKey
  auth.setKey(candidate)
  try {
    await api.getConfig() // cheap authenticated call
    key.value = ''
    auth.required = false
    auth.fetchInfo().catch(() => {})
    if (previous === candidate) events.restart() // key unchanged: the store watcher will not fire
  } catch (e) {
    if (e?.status === 401) {
      auth.clearKey()
      auth.markRequired()
      error.value = 'That key was not accepted.'
    } else {
      error.value = e?.message || 'Could not verify the key.'
      auth.markRequired()
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <UiModal :open="auth.required" title="API key required" :closable="false">
    <form id="api-key-form" class="flex flex-col gap-3" @submit.prevent="submit">
      <p class="text-sm text-camera-muted">
        This server is protected. Enter the API key to continue. If you lost it, delete
        <code>data/api_key.json</code> on the host.
      </p>
      <UiText
        v-model="key"
        type="password"
        label="API key"
        placeholder="Paste key"
        data-autofocus
      />
      <p v-if="error" class="text-sm text-red-400" role="alert" data-test="error">{{ error }}</p>
    </form>
    <template #footer>
      <UiButton
        type="submit"
        form="api-key-form"
        variant="primary"
        :loading="loading"
        :disabled="!key.trim()"
      >
        Unlock
      </UiButton>
    </template>
  </UiModal>
</template>
