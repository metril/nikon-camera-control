<script setup>
/**
 * Sign-in. Shown whenever the server wants credentials (`auth.required`). With an app password it
 * asks for that; while only an API key protects the app it asks for the key. Works with the
 * on-screen keyboard (touch) and Enter (desktop). The server's message is shown verbatim.
 */
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'
import UiModal from '@/components/ui/UiModal.vue'
import UiText from '@/components/ui/UiText.vue'
import UiButton from '@/components/ui/UiButton.vue'

const auth = useAuthStore()
const config = useConfigStore()
const secret = ref('')
const error = ref('')
const loading = ref(false)

const keyMode = computed(() => !!auth.status && !auth.status.password_set)
const label = computed(() => (keyMode.value ? 'API key' : 'Password'))

async function submit() {
  const value = keyMode.value ? secret.value.trim() : secret.value
  if (!value || loading.value) return
  loading.value = true
  error.value = ''
  auth.pairError = ''
  try {
    await auth.login(keyMode.value ? { api_key: value } : { password: value })
    secret.value = ''
    // Data requested before signing in failed with 401: reload what the views read once.
    config.fetch().catch(() => {})
    config.fetchSchema().catch(() => {})
    auth.fetchInfo().catch(() => {})
  } catch (e) {
    error.value = e?.message || 'Could not sign in.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <UiModal :open="auth.required" title="Sign in" :closable="false">
    <form id="login-form" class="flex flex-col gap-3" @submit.prevent="submit">
      <p class="text-sm text-camera-muted">
        {{
          keyMode
            ? 'This camera is protected by an API key. Enter it to continue.'
            : 'This camera is protected. Enter the app password to continue.'
        }}
      </p>
      <UiText
        v-model="secret"
        type="password"
        :label="label"
        :placeholder="keyMode ? 'Paste key' : 'Password'"
        data-autofocus
      />
      <p
        v-if="error || auth.pairError"
        class="text-sm text-camera-danger"
        role="alert"
        data-test="error"
      >
        {{ error || auth.pairError }}
      </p>
    </form>
    <template #footer>
      <UiButton
        type="submit"
        form="login-form"
        variant="primary"
        :loading="loading"
        :disabled="!secret.trim()"
        data-test="signin"
      >
        Sign in
      </UiButton>
    </template>
  </UiModal>
</template>
