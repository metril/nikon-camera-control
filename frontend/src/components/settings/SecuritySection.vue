<script setup>
/**
 * Security: the app password (set, change, remove), signed-in sessions, the API key for scripts
 * and the kiosk device token. Server messages (wrong password, rate limit) are shown verbatim.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiText from '@/components/ui/UiText.vue'

const auth = useAuthStore()
const config = useConfigStore()
const toasts = useToastsStore()

// ---------------------------------------------------------------- password
const passwordSet = computed(() => !!auth.status?.password_set)
const current = ref('')
const next = ref('')
const confirm = ref('')
const pwBusy = ref(false)
const pwError = ref('')
const mismatch = computed(() => !!confirm.value && next.value !== confirm.value)

async function runPassword(fn, done) {
  pwBusy.value = true
  pwError.value = ''
  try {
    await fn()
    current.value = next.value = confirm.value = ''
    toasts.success(done)
    await loadSessions()
  } catch (e) {
    pwError.value = e?.message || 'Could not change the password.'
  } finally {
    pwBusy.value = false
  }
}
const savePassword = () =>
  runPassword(
    () => auth.setPassword({ current: current.value, next: next.value }),
    passwordSet.value ? 'Password changed' : 'Password set',
  )
const removePassword = () =>
  runPassword(() => auth.removePassword(current.value), 'Password removed')

// ---------------------------------------------------------------- sessions
const sessions = ref([])
const sessBusy = ref(false)
const protectedNow = computed(() => !!auth.status?.auth_required)

async function loadSessions() {
  if (!protectedNow.value || !auth.status?.authenticated) {
    sessions.value = []
    return
  }
  try {
    sessions.value = (await api.listAuthSessions()).sessions
  } catch {
    sessions.value = []
  }
}
async function run(fn, ok) {
  sessBusy.value = true
  try {
    const out = await fn()
    if (ok) toasts.success(typeof ok === 'function' ? ok(out) : ok)
    await loadSessions()
  } catch (e) {
    toasts.error(e)
  } finally {
    sessBusy.value = false
  }
}
const revoke = (s) =>
  run(() => api.revokeAuthSession({ path: { session_id: s.id } }), 'Session signed out')
const revokeAll = () =>
  run(
    () => api.revokeAllAuthSessions(),
    (o) => `${o?.revoked ?? 0} other session${o?.revoked === 1 ? '' : 's'} signed out`,
  )
const rotateKiosk = () =>
  run(() => api.rotateKioskToken(), 'Kiosk token rotated. The kiosk pairs again by itself.')
const when = (iso) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}
onMounted(loadSessions)
watch(() => [auth.status?.auth_required, auth.status?.authenticated], loadSessions)

// ---------------------------------------------------------------- API key (for scripts)
const keySet = computed(() => config.config?.api_key_set ?? !!auth.status?.api_key_set)
const keyBusy = ref(false)
const newKey = ref('')
const copied = ref(false)

async function runKey(fn) {
  keyBusy.value = true
  try {
    return await fn()
  } catch (e) {
    toasts.error(e)
  } finally {
    keyBusy.value = false
  }
}
const generate = () =>
  runKey(async () => {
    copied.value = false
    newKey.value = await config.createApiKey()
  })
const removeKey = () =>
  runKey(() => config.deleteApiKey().then(() => toasts.success('API key removed')))

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
  <div class="flex shrink-0 flex-col gap-4" data-test="security">
    <UiCard
      title="App password"
      subtitle="Signs browsers in. Anyone on the network needs it to control the camera."
    >
      <template #actions>
        <UiBadge :tone="passwordSet ? 'ok' : 'warn'" data-test="password-status">
          {{ passwordSet ? 'Password set' : 'Not set' }}
        </UiBadge>
      </template>
      <form class="flex max-w-md flex-col gap-3" @submit.prevent="savePassword">
        <UiText
          v-if="passwordSet"
          v-model="current"
          type="password"
          label="Current password"
          data-test="current"
        />
        <UiText
          v-model="next"
          type="password"
          :label="passwordSet ? 'New password' : 'Password'"
          data-test="new"
        />
        <UiText v-model="confirm" type="password" label="Repeat password" data-test="confirm" />
        <p v-if="mismatch" class="text-sm text-camera-danger" data-test="mismatch">
          The passwords do not match.
        </p>
        <p v-if="pwError" class="text-sm text-camera-danger" role="alert" data-test="pw-error">
          {{ pwError }}
        </p>
        <div class="flex flex-wrap gap-2">
          <UiButton
            type="submit"
            variant="primary"
            :loading="pwBusy"
            :disabled="!next || next !== confirm || (passwordSet && !current)"
            data-test="save-password"
          >
            {{ passwordSet ? 'Change password' : 'Set password' }}
          </UiButton>
          <UiConfirmButton
            v-if="passwordSet"
            variant="danger"
            confirm-text="Remove password?"
            :disabled="pwBusy || !current"
            :title="current ? '' : 'Enter the current password to remove it'"
            data-test="remove-password"
            @confirm="removePassword"
          >
            Remove password
          </UiConfirmButton>
        </div>
        <p class="text-xs text-camera-muted">
          Removing the password opens the camera to everyone on the network. Locked out? Delete
          <code>data/password.json</code> on the host.
        </p>
      </form>
    </UiCard>

    <UiCard
      v-if="protectedNow"
      title="Signed-in sessions"
      subtitle="Browsers and kiosks that are signed in."
    >
      <template #actions>
        <UiConfirmButton
          confirm-text="Sign out all?"
          :loading="sessBusy"
          data-test="revoke-all"
          @confirm="revokeAll"
        >
          Sign out all other sessions
        </UiConfirmButton>
      </template>
      <ul class="scroll-panel flex max-h-56 flex-col gap-2" data-test="sessions">
        <li
          v-for="s in sessions"
          :key="s.id"
          class="flex items-center gap-3 text-sm"
          :data-session="s.id"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="font-medium">{{ s.kind === 'kiosk' ? 'Kiosk' : 'Browser' }}</span>
              <UiBadge v-if="s.current" tone="ok">This session</UiBadge>
            </div>
            <div class="truncate text-xs text-camera-muted" :title="s.user_agent || ''">
              {{ s.user_agent || 'Unknown device' }} · last seen {{ when(s.last_seen) }}
            </div>
          </div>
          <UiButton
            v-if="!s.current"
            size="sm"
            :disabled="sessBusy"
            data-test="revoke"
            @click="revoke(s)"
          >
            Sign out
          </UiButton>
        </li>
        <li v-if="!sessions.length" class="text-sm text-camera-muted">No sessions.</li>
      </ul>
    </UiCard>

    <UiCard
      title="API key"
      subtitle="For scripts and other programs (X-API-Key header). Browsers sign in with the password."
    >
      <template #actions>
        <UiBadge :tone="keySet ? 'ok' : 'neutral'" data-test="key-status">
          {{ keySet ? 'Key set' : 'Not set' }}
        </UiBadge>
      </template>
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap gap-2">
          <UiConfirmButton
            v-if="keySet"
            confirm-text="Rotate key?"
            :loading="keyBusy"
            data-test="rotate"
            @confirm="generate"
          >
            Rotate key
          </UiConfirmButton>
          <UiButton
            v-else
            variant="primary"
            :loading="keyBusy"
            data-test="generate"
            @click="generate"
          >
            Generate key
          </UiButton>
          <UiConfirmButton
            v-if="keySet"
            variant="danger"
            confirm-text="Remove key?"
            :disabled="keyBusy"
            data-test="remove"
            @confirm="removeKey"
          >
            Remove key
          </UiConfirmButton>
        </div>
        <p class="text-xs text-camera-muted">
          Locked out? Delete <code>data/api_key.json</code> on the host and restart to remove the
          key.
        </p>
      </div>
    </UiCard>

    <UiCard
      title="Kiosk"
      subtitle="The touch screen on the camera signs itself in with a device token."
    >
      <div class="flex flex-col gap-3">
        <div>
          <UiConfirmButton
            confirm-text="Rotate token?"
            :loading="sessBusy"
            data-test="rotate-kiosk"
            @confirm="rotateKiosk"
          >
            Rotate kiosk token
          </UiConfirmButton>
        </div>
        <p class="text-xs text-camera-muted">
          Signs the kiosk out and gives it a new token. It pairs again on its own.
        </p>
      </div>
    </UiCard>

    <UiModal :open="!!newKey" title="Your new API key" :closable="false">
      <p class="mb-2 text-sm">Copy this key now. It is shown only once.</p>
      <code class="block break-all rounded bg-camera-bg p-3 text-sm" data-test="new-key">{{
        newKey
      }}</code>
      <template #footer>
        <UiButton data-test="copy" @click="copy">{{ copied ? 'Copied' : 'Copy' }}</UiButton>
        <UiButton variant="primary" data-test="saved" @click="saved">I've saved it</UiButton>
      </template>
    </UiModal>
  </div>
</template>
