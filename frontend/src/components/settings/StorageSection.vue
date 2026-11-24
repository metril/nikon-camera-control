<script setup>
import { ref, computed, onMounted } from 'vue'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import UiCard from '@/components/ui/UiCard.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiText from '@/components/ui/UiText.vue'
import { formatBytes } from '@/components/shell/format'
import OffloadDialog from './OffloadDialog.vue'

const storage = useStorageStore()
const toasts = useToastsStore()

const busy = ref({}) // `${action}:${id}` -> true
const fsck = ref({}) // id -> {returncode, output}
const offloadOpen = ref(false)
const form = ref({ name: '', unc: '', username: '', password: '', domain: '' })
const testResult = ref(null)
const adding = ref(false)
const testing = ref(false)

const usb = computed(() => storage.locations.filter((l) => l.kind === 'usb'))
const smb = computed(() => storage.locations.filter((l) => l.kind === 'smb'))
const configured = computed(() => storage.locations.filter((l) => l.configured))
const backupChoices = computed(() => configured.value.filter((l) => l.id !== storage.targetId))
const backup = computed(() => storage.backup)
const label = (l) => l.name || l.label || l.id
const smbBody = () => {
  const f = form.value
  const b = { unc: f.unc.trim() }
  if (f.username) b.username = f.username
  if (f.password) b.password = f.password
  if (f.domain) b.domain = f.domain
  return b
}

async function run(key, fn, ok) {
  busy.value = { ...busy.value, [key]: true }
  try {
    const r = await fn()
    if (ok) toasts.success(ok)
    return r
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = { ...busy.value, [key]: false }
  }
}
const isBusy = (action, id = '') => !!busy.value[`${action}:${id}`]
const mount = (l) => run(`mount:${l.id}`, () => storage.mount(l.id), `${label(l)} mounted`)
const unmount = (l) => run(`unmount:${l.id}`, () => storage.unmount(l.id), `${label(l)} unmounted`)
const register = (l) =>
  run(`add:${l.id}`, () => storage.add({ kind: 'usb', uuid: l.uuid, name: l.label || '' }))
const forget = (l) => run(`remove:${l.id}`, () => storage.remove(l.id), `${label(l)} removed`)
const check = (l) =>
  run(`check:${l.id}`, async () => {
    fsck.value = { ...fsck.value, [l.id]: await storage.check(l.id) }
  })
const setTarget = (id) => run('target', () => storage.setTarget(id))
function toggleBackup(id, on) {
  const ids = new Set(storage.backupIds)
  on ? ids.add(id) : ids.delete(id)
  return run('backups', () => storage.setBackups([...ids]))
}
const backupNow = () => run('backup', () => storage.runBackup(), 'Backup started')
const actionHint = computed(() => {
  if (!storage.targetId) return 'Choose a storage location first to back up or verify.'
  if (!storage.backupIds.length) return 'Choose a backup location to back up now.'
  if (storage.mounted.length < 2) return 'Offload needs two mounted locations.'
  return ''
})
const verify = () => run('verify', () => storage.verify({}), 'Verify started. Progress is in Jobs.')

async function test() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await storage.testSmb(smbBody())
  } catch (e) {
    toasts.error(e)
  } finally {
    testing.value = false
  }
}
async function addSmb() {
  adding.value = true
  try {
    await storage.add({
      kind: 'smb',
      name: form.value.name.trim(),
      ...smbBody(),
    })
    form.value = { name: '', unc: '', username: '', password: '', domain: '' }
    testResult.value = null
    toasts.success('Share added')
  } catch (e) {
    toasts.error(e)
  } finally {
    adding.value = false
  }
}

onMounted(() => storage.refresh().catch((e) => toasts.error(e)))
</script>

<template>
  <UiCard
    title="Storage"
    subtitle="Where captures are saved, plus backups. Mounted drives only."
    data-section="storage-locations"
  >
    <div class="flex flex-col gap-5">
      <p v-if="storage.noTarget" class="text-sm text-camera-warn" data-test="no-target-hint">
        No storage target. Mount a drive and choose it below.
      </p>

      <section
        v-for="grp in [
          ['USB drives', usb, 'usb'],
          ['Network shares (SMB)', smb, 'smb'],
        ]"
        :key="grp[2]"
      >
        <h3 class="eyebrow mb-2">{{ grp[0] }}</h3>
        <p v-if="!grp[1].length" class="text-sm text-camera-muted" :data-test="`none-${grp[2]}`">
          {{ grp[2] === 'usb' ? 'No drives detected.' : 'No shares configured.' }}
        </p>
        <ul class="flex flex-col gap-2">
          <li
            v-for="l in grp[1]"
            :key="l.id"
            class="rounded-inner border border-camera-border p-3"
            :data-test="`loc-${l.id}`"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span class="min-w-0 break-all font-medium">{{ label(l) }}</span>
              <UiBadge :tone="l.mounted ? 'ok' : 'neutral'">{{
                l.mounted ? 'Mounted' : 'Not mounted'
              }}</UiBadge>
              <UiBadge v-if="l.is_target" tone="accent">Photo location</UiBadge>
              <UiBadge v-if="l.is_backup" tone="accent">Backup</UiBadge>
              <UiBadge v-if="!l.supported" tone="warn" data-test="unsupported">Unsupported</UiBadge>
              <UiBadge
                v-if="l.kind === 'smb' && l.mounted && l.encrypted === false"
                tone="warn"
                title="This share does not support SMB3 encryption; traffic is not encrypted"
                data-test="unencrypted"
                >Unencrypted</UiBadge
              >
              <UiBadge v-if="l.kind === 'usb' && !l.present" tone="warn">Not connected</UiBadge>
            </div>
            <p class="mt-1 text-xs text-camera-muted">
              <template v-if="l.fstype">{{ l.fstype }} · </template>
              <template v-if="l.unc">{{ l.unc }} · </template>
              <template v-if="l.size != null">{{ formatBytes(l.size) }} total</template>
              <template v-if="l.mounted && l.free != null">
                · {{ formatBytes(l.free) }} free</template
              >
            </p>
            <p v-if="l.reason" class="mt-1 text-xs text-camera-warn">{{ l.reason }}</p>
            <p
              v-if="l.error"
              class="mt-1 break-words text-xs text-camera-danger"
              data-test="loc-error"
            >
              {{ l.error }}
            </p>
            <div class="mt-2 flex flex-wrap gap-2">
              <UiButton
                v-if="!l.configured"
                size="sm"
                variant="primary"
                :disabled="!l.supported"
                :loading="isBusy('add', l.id)"
                data-test="register"
                @click="register(l)"
                >Add</UiButton
              >
              <template v-else>
                <UiButton
                  v-if="!l.mounted"
                  size="sm"
                  variant="primary"
                  :disabled="!l.supported || (l.kind === 'usb' && !l.present)"
                  :loading="isBusy('mount', l.id)"
                  data-test="mount"
                  @click="mount(l)"
                  >Mount</UiButton
                >
                <UiConfirmButton
                  v-else
                  size="sm"
                  confirm-text="Unmount?"
                  :loading="isBusy('unmount', l.id)"
                  data-test="unmount"
                  @confirm="unmount(l)"
                  >Unmount</UiConfirmButton
                >
                <UiConfirmButton
                  v-if="l.kind === 'usb'"
                  size="sm"
                  confirm-text="Run check?"
                  :disabled="l.mounted"
                  :loading="isBusy('check', l.id)"
                  data-test="fsck"
                  @confirm="check(l)"
                  >Check &amp; repair</UiConfirmButton
                >
                <UiConfirmButton
                  v-if="l.kind === 'smb'"
                  size="sm"
                  variant="ghost"
                  confirm-text="Remove?"
                  :disabled="l.is_target"
                  :loading="isBusy('remove', l.id)"
                  data-test="forget"
                  @confirm="forget(l)"
                  >Remove</UiConfirmButton
                >
              </template>
            </div>
            <pre
              v-if="fsck[l.id]"
              class="mt-2 max-h-40 overflow-auto rounded-inner bg-camera-bg p-2 text-xs"
              data-test="fsck-out"
              >{{ fsck[l.id].output || `exit ${fsck[l.id].returncode}` }}</pre>
          </li>
        </ul>
      </section>

      <section>
        <h3 class="eyebrow mb-2">Add SMB share</h3>
        <form class="grid gap-3 sm:grid-cols-2" @submit.prevent="addSmb">
          <UiText
            v-model="form.unc"
            label="Share (//host/share)"
            placeholder="//nas/photos"
            class="sm:col-span-2"
          />
          <UiText v-model="form.name" label="Name" :maxlength="64" placeholder="Optional" />
          <UiText v-model="form.domain" label="Domain" placeholder="Optional" />
          <UiText v-model="form.username" label="User" />
          <UiText
            v-model="form.password"
            label="Password"
            type="password"
            placeholder="Saved but never shown"
          />
          <div class="flex flex-wrap items-center gap-2 sm:col-span-2">
            <UiButton
              :disabled="!form.unc.trim()"
              :loading="testing"
              data-test="smb-test"
              @click="test"
              >Test</UiButton
            >
            <UiButton
              type="submit"
              variant="primary"
              :disabled="!form.unc.trim()"
              :loading="adding"
              data-test="smb-add"
              >Add share</UiButton
            >
            <span v-if="!form.unc.trim()" class="text-xs text-camera-muted" data-test="smb-hint"
              >Enter a share path to test or add it.</span
            >
            <span
              v-if="testResult"
              class="text-sm"
              :class="testResult.ok ? 'text-camera-ok' : 'text-camera-danger'"
              data-test="smb-result"
              >{{ testResult.message }}</span
            >
          </div>
        </form>
      </section>

      <section v-if="configured.length">
        <h3 class="eyebrow mb-2">Roles</h3>
        <fieldset class="mb-3" data-test="target-group">
          <legend class="mb-1 text-sm font-medium">Copy each photo to</legend>
          <label
            v-for="l in storage.mounted.filter((x) => x.configured)"
            :key="l.id"
            class="flex items-center gap-2 py-1 text-sm"
          >
            <input
              type="radio"
              name="target"
              :value="l.id"
              :checked="storage.targetId === l.id"
              :disabled="isBusy('target')"
              :data-test="`target-${l.id}`"
              @change="setTarget(l.id)"
            />
            {{ label(l) }}
          </label>
          <p v-if="!storage.mounted.length" class="text-sm text-camera-muted">
            Mount a drive to choose it.
          </p>
        </fieldset>
        <fieldset data-test="backup-group">
          <legend class="mb-1 text-sm font-medium">Backups</legend>
          <label
            v-for="l in backupChoices"
            :key="l.id"
            class="flex items-center gap-2 py-1 text-sm"
          >
            <input
              type="checkbox"
              :checked="storage.backupIds.includes(l.id)"
              :disabled="isBusy('backups')"
              :data-test="`backup-${l.id}`"
              @change="toggleBackup(l.id, $event.target.checked)"
            />
            {{ label(l) }}
            <UiBadge v-if="!l.mounted" tone="warn">Offline</UiBadge>
          </label>
          <p v-if="!backupChoices.length" class="text-sm text-camera-muted">
            Nothing else to back up to.
          </p>
        </fieldset>
      </section>

      <section class="flex flex-col gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <UiButton
            :disabled="!storage.backupIds.length || !storage.targetId"
            :loading="isBusy('backup')"
            data-test="backup-now"
            @click="backupNow"
            >Back up now</UiButton
          >
          <UiButton
            :disabled="!storage.targetId"
            :loading="isBusy('verify')"
            data-test="verify"
            @click="verify"
            >Verify photo location</UiButton
          >
          <UiButton
            :disabled="storage.mounted.length < 2"
            data-test="offload-open"
            @click="offloadOpen = true"
            >Offload…</UiButton
          >
        </div>
        <p v-if="actionHint" class="text-xs text-camera-muted" data-test="action-hint">
          {{ actionHint }}
        </p>
        <p v-if="backup" class="text-xs text-camera-muted" data-test="backup-status">
          <template v-if="backup.running"
            >Backing up{{ backup.current ? `: ${backup.current}` : '' }}.
          </template>
          {{ backup.pending }} pending · {{ backup.copied }} copied · {{ backup.failed }} failed
          <template v-if="backup.last_error"> · {{ backup.last_error }}</template>
        </p>
      </section>
    </div>
    <OffloadDialog :open="offloadOpen" @close="offloadOpen = false" />
  </UiCard>
</template>
