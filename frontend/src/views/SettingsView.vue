<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'
import { useCameraStore } from '@/stores/camera'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { useKeyboardHints } from '@/composables/useKeyboardHints'
import { captureTarget, sampleName } from '@/labels'
import UiText from '@/components/ui/UiText.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import SchemaField from '@/components/settings/SchemaField.vue'
import SettingRow from '@/components/settings/SettingRow.vue'
import SettingsSection from '@/components/settings/SettingsSection.vue'
import CameraClockRow from '@/components/settings/CameraClockRow.vue'
import ApiKeySection from '@/components/settings/ApiKeySection.vue'
import DemoCameraSection from '@/components/settings/DemoCameraSection.vue'
import StorageSection from '@/components/settings/StorageSection.vue'
import AboutSection from '@/components/settings/AboutSection.vue'
import {
  buildSections,
  buildPatch,
  dirtyPaths,
  fieldErrors,
  getPath,
  setPath,
  pathTitles,
  titleForPath,
} from '@/components/settings/schemaForm'

const config = useConfigStore()
const toasts = useToastsStore()
const storage = useStorageStore()
const camera = useCameraStore()
const admin = useCameraAdminStore()
const { pref: layoutPref, setPref: setLayoutPref } = useLayoutMode()
const { hints, setHints } = useKeyboardHints()

const draft = ref({})
let base = {} // server config the draft was last synced to
const errors = ref({})
const saving = ref(false)
const resetting = ref(false)
const loadError = ref('')

// Storage locations/target/backups are managed by StorageSection, not the generic form.
const STORAGE_OWNED = ['locations', 'target_id', 'backup_ids']
// Shown in the Capture section instead of their own section.
// Shown in Display.
const DISPLAY_OWNED = ['timezone']
const CAPTURE_OWNED = ['camera.keep_card_copy', 'camera.download_photos', 'camera.filename_prefix']
const sections = computed(() =>
  buildSections(config.schema).map((s) =>
    s.key === 'storage'
      ? { ...s, fields: s.fields.filter((f) => !STORAGE_OWNED.includes(f.name)) }
      : s,
  ),
)
const shownSections = computed(() =>
  sections.value
    .map((s) => ({
      ...s,
      fields: s.fields.filter(
        (f) => !CAPTURE_OWNED.includes(s.path(f)) && !DISPLAY_OWNED.includes(s.path(f)),
      ),
    }))
    .filter((s) => s.fields.length || s.key === 'camera'),
)
const keepCardField = computed(() =>
  sections.value.find((s) => s.key === 'camera')?.fields.find((f) => f.name === 'keep_card_copy'),
)
// Downloads off = trigger only: the camera must save to its card or the photos would be lost.
const downloads = computed(() => getPath(draft.value, 'camera.download_photos') !== false)
const prefix = computed(() => getPath(draft.value, 'camera.filename_prefix') || '')
const example = computed(() => sampleName(prefix.value))
const cardChoice = () => (admin.target?.choices || []).find((c) => !/ram|internal/i.test(c))
const onCard = () => !/ram|internal/i.test(String(admin.target?.value || ''))
async function setDownloads(on) {
  if (!on && admin.target && !onCard()) {
    if (targetReason.value || !cardChoice()) {
      toasts.error('Switch the camera to the memory card first, then turn downloads off.')
      return
    }
    await setCameraTarget(cardChoice())
    if (!onCard()) return
  }
  setPath(draft.value, 'camera.download_photos', on)
}
const titles = computed(() => () => pathTitles(sections.value))
const titled = (paths) => paths.map((p) => titleForPath(titles.value, p)).join(', ')

const dirty = computed(() =>
  config.config ? dirtyPaths(sections.value, config.config, draft.value, ['demo_camera']) : [],
)
const isDirty = computed(() => dirty.value.length > 0)
const clone = (o) => JSON.parse(JSON.stringify(o ?? {}))
function sync() {
  base = clone(config.config)
  draft.value = clone(config.config)
}

// Follow server-side changes (config_changed events) unless the user has unsaved edits.
watch(
  () => config.config,
  (c) => {
    // Compare against the config the draft was synced to: `isDirty` already reflects `c`.
    if (c && !dirtyPaths(sections.value, base, draft.value, ['demo_camera']).length) sync()
  },
  { deep: true },
)

async function load() {
  loadError.value = ''
  try {
    await Promise.all([config.fetch(), config.schema ? null : config.fetchSchema()])
    sync()
  } catch (e) {
    loadError.value = e?.message || 'Could not load settings'
  }
}
onMounted(() => {
  load()
  if (!storage.loaded) storage.fetch().catch(() => {})
})

const value = (s, f) => getPath(draft.value, s.path(f))
const setValue = (s, f, v) => {
  setPath(draft.value, s.path(f), v)
  delete errors.value[s.path(f)]
}
const isFieldDirty = (path) => dirty.value.includes(path)

async function save() {
  saving.value = true
  errors.value = {}
  try {
    await config.patch(buildPatch(dirty.value, draft.value))
    sync()
    toasts.success('Settings saved')
  } catch (e) {
    const fe = e?.status === 422 ? fieldErrors(e.details) : {}
    errors.value = fe
    if (Object.keys(fe).length)
      toasts.error('Some settings are invalid. See the highlighted fields.')
    else toasts.error(e)
  } finally {
    saving.value = false
  }
}
function discard() {
  sync()
  errors.value = {}
}
async function resetDefaults() {
  resetting.value = true
  try {
    await config.reset()
    sync()
    errors.value = {}
    toasts.success('Settings reset to defaults')
  } catch (e) {
    toasts.error(e)
  } finally {
    resetting.value = false
  }
}

// Display
const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone
const zoneNames = (() => {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return []
  }
})()
const zone = computed(() => getPath(draft.value, 'timezone') || '')
const zoneOptions = computed(() => {
  const names = new Set(zoneNames)
  for (const z of [zone.value, browserZone]) if (z) names.add(z)
  return [
    { value: '', label: 'Server default' },
    ...[...names].sort().map((z) => ({ value: z, label: z.replace(/_/g, ' ') })),
  ]
})
const setZone = (v) => {
  setPath(draft.value, 'timezone', v || null)
  delete errors.value.timezone
}
const LAYOUTS = [
  { value: 'auto', label: 'Auto' },
  { value: 'desktop', label: 'Desktop' },
  { value: 'touch', label: 'Touch' },
]

// Capture: where the camera saves (applied at once, like the camera settings)
const savingTarget = ref(false)
const targetOptions = computed(() =>
  (admin.target?.choices || []).map((c) => ({ value: c, label: captureTarget(c) })),
)
const targetReason = computed(() => {
  if (!camera.connected) return 'Connect the camera to change this.'
  if (camera.state === 'recording' || camera.leasedBy) return 'Not while the camera is busy.'
  return ''
})
watch(
  () => camera.connected,
  (on) => {
    if (on && !admin.target) admin.fetchTarget().catch(() => {})
  },
  { immediate: true },
)
async function setCameraTarget(v) {
  if (!v || v === admin.target?.value) return
  savingTarget.value = true
  try {
    await admin.setTarget(v)
  } catch (e) {
    toasts.error(e)
    admin.fetchTarget().catch(() => {})
  } finally {
    savingTarget.value = false
  }
}

// Capture: where every photo is copied
const savingLocation = ref(false)
const locationOptions = computed(() =>
  storage.mounted
    .filter((l) => l.configured)
    .map((l) => ({ value: l.id, label: l.name || l.label || l.id })),
)
async function setLocation(id) {
  if (!id || id === storage.targetId) return
  savingLocation.value = true
  try {
    await storage.setTarget(id)
  } catch (e) {
    toasts.error(e)
  } finally {
    savingLocation.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-[760px] flex-col gap-4">
    <h2 class="text-xl font-semibold">Settings</h2>

    <UiAlert
      v-if="config.restartRequired.length"
      tone="warn"
      title="Restart required"
      data-test="restart"
    >
      Changes to {{ titled(config.restartRequired) }} take effect after the app restarts.
      <template #action>
        <UiButton size="sm" data-test="dismiss-restart" @click="config.dismissRestart()">
          Dismiss
        </UiButton>
      </template>
    </UiAlert>

    <UiEmpty v-if="loadError" title="Settings could not be loaded" :hint="loadError">
      <template #actions><UiButton variant="primary" @click="load">Retry</UiButton></template>
    </UiEmpty>

    <template v-else-if="config.config && sections.length">
      <SettingsSection title="Display" data-section="display">
        <SettingRow
          title="Layout"
          description="Auto picks the touch layout on touch screens. Saved in this browser only."
        >
          <UiSegmented
            :model-value="layoutPref"
            :options="LAYOUTS"
            aria-label="Layout"
            data-test="layout"
            @update:model-value="setLayoutPref"
          />
        </SettingRow>
        <SettingRow
          title="Time zone"
          description="Used for photo and session names and when setting the camera clock."
          :dirty="isFieldDirty('timezone')"
          :error="errors.timezone || ''"
          data-field="timezone"
        >
          <UiSelect
            :model-value="zone"
            :options="zoneOptions"
            label="Time zone"
            data-test="timezone"
            @update:model-value="setZone"
          />
          <template #note>
            <UiButton
              v-if="browserZone && zone !== browserZone"
              size="sm"
              data-test="timezone-browser"
              @click="setZone(browserZone)"
            >
              Use this browser's time zone ({{ browserZone }})
            </UiButton>
          </template>
        </SettingRow>
        <SettingRow
          title="Keyboard hints"
          description="Show shortcut hints such as Space to capture."
          natural
        >
          <UiToggle
            :model-value="hints"
            aria-label="Keyboard hints"
            data-test="hints"
            @update:model-value="setHints"
          />
        </SettingRow>
      </SettingsSection>

      <SettingsSection title="Capture" data-section="capture">
        <SettingRow
          title="Camera saves to"
          description="Memory card is the safest. Camera memory is faster but keeps no copy on the card."
        >
          <UiSelect
            :model-value="admin.target?.value"
            :options="targetOptions"
            label="Camera saves to"
            :disabled="!downloads || !!targetReason || savingTarget || !targetOptions.length"
            data-test="camera-target"
            @update:model-value="setCameraTarget"
          />
          <template #note>
            <span v-if="!downloads" data-test="target-locked">
              Locked to memory card while downloads are off, so photos aren't lost.
            </span>
            <span v-else-if="targetReason" data-test="target-reason">{{ targetReason }}</span>
          </template>
        </SettingRow>
        <SettingRow
          title="Download photos"
          description="Turn off to only fire the shutter. Photos stay on the camera's card and Shoot is ready for the next shot sooner."
          :dirty="isFieldDirty('camera.download_photos')"
          natural
          data-field="download_photos"
        >
          <UiToggle
            :model-value="downloads"
            aria-label="Download photos"
            data-test="download-photos"
            @update:model-value="setDownloads"
          />
        </SettingRow>
        <SettingRow
          title="Copy each photo to"
          description="Every photo is copied here, whichever option the camera uses."
        >
          <UiSelect
            :model-value="storage.targetId"
            :options="locationOptions"
            label="Copy each photo to"
            :disabled="!downloads || savingLocation || !locationOptions.length"
            data-test="photo-location"
            @update:model-value="setLocation"
          />
          <template #note>
            <span v-if="!locationOptions.length" data-test="location-reason">
              Mount a drive or share below to choose it.
            </span>
          </template>
        </SettingRow>
        <SettingRow
          title="File name prefix"
          description="Added to the start of every downloaded photo's name. Up to 40 characters; spaces and symbols become dashes."
          :dirty="isFieldDirty('camera.filename_prefix')"
          :error="errors['camera.filename_prefix'] || ''"
          data-field="filename_prefix"
        >
          <UiText
            :model-value="prefix"
            label="File name prefix"
            placeholder="e.g. wedding"
            :maxlength="40"
            :disabled="!downloads"
            data-test="filename-prefix"
            @update:model-value="setPath(draft, 'camera.filename_prefix', $event || null)"
          />
          <template #note>
            <span v-if="!downloads" data-test="prefix-unused">
              Not used while photos stay on the card.
            </span>
            <span v-else data-test="prefix-example">
              Saved as
              <span class="font-mono"
                ><span class="text-camera-accent">{{ example[0] }}</span
                >{{ example[1] }}</span
              >
            </span>
          </template>
        </SettingRow>
        <SchemaField
          v-if="keepCardField"
          :field="keepCardField"
          :class="{ 'pointer-events-none opacity-[.45]': !downloads }"
          :aria-disabled="!downloads || undefined"
          :model-value="getPath(draft, 'camera.keep_card_copy')"
          :dirty="isFieldDirty('camera.keep_card_copy')"
          :error="errors['camera.keep_card_copy'] || ''"
          @update:model-value="setPath(draft, 'camera.keep_card_copy', $event)"
        />
      </SettingsSection>

      <StorageSection />

      <SettingsSection
        v-for="s in shownSections"
        :key="s.key"
        :title="s.title"
        :subtitle="s.description"
        :data-section="s.key"
      >
        <SchemaField
          v-for="f in s.fields"
          :key="s.path(f)"
          :field="f"
          :model-value="value(s, f)"
          :dirty="isFieldDirty(s.path(f))"
          :error="errors[s.path(f)] || ''"
          @update:model-value="setValue(s, f, $event)"
        />
        <CameraClockRow v-if="s.key === 'camera'" />
      </SettingsSection>

      <DemoCameraSection
        :model-value="!!draft.demo_camera"
        :dirty="isFieldDirty('demo_camera')"
        @update:model-value="draft.demo_camera = $event"
      />
      <ApiKeySection />

      <UiAlert
        v-if="config.resetChanged?.length"
        tone="info"
        title="Reset changed"
        data-test="reset-changed"
      >
        {{ titled(config.resetChanged) }}
      </UiAlert>

      <div class="flex flex-wrap items-center gap-3">
        <UiConfirmButton
          variant="danger"
          size="sm"
          confirm-text="Reset everything?"
          :loading="resetting"
          data-test="reset"
          @confirm="resetDefaults"
        >
          Reset to defaults
        </UiConfirmButton>
        <p class="min-w-0 flex-1 text-xs text-camera-muted">
          Restores every setting, including the demo camera switch.
        </p>
      </div>
    </template>
    <p v-else class="text-sm text-camera-muted" aria-live="polite">Loading settings…</p>

    <AboutSection />

    <div
      v-if="config.config && isDirty"
      class="sticky bottom-[var(--nav,0px)] z-[15] flex flex-wrap items-center gap-3 rounded-t-card border border-b-0 border-camera-border bg-camera-raised px-4 py-2 shadow-[0_-8px_24px_rgba(0,0,0,.4)] max-[420px]:gap-2"
      data-test="savebar"
    >
      <span class="whitespace-nowrap text-sm tabular-nums" aria-live="polite">
        {{ dirty.length }} unsaved change{{ dirty.length === 1 ? '' : 's' }}
      </span>
      <span class="flex-1 max-[420px]:hidden" />
      <UiButton
        variant="ghost"
        size="sm"
        :disabled="saving"
        class="max-[420px]:flex-1"
        data-test="discard"
        @click="discard"
      >
        Discard
      </UiButton>
      <UiButton
        variant="primary"
        size="sm"
        :loading="saving"
        class="max-[420px]:flex-1"
        data-test="save"
        @click="save"
      >
        Save changes
      </UiButton>
    </div>
  </div>
</template>
