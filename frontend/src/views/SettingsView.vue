<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, provide, reactive } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'
import { useCameraStore } from '@/stores/camera'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { routeQuery } from '@/components/shell/useTabs'
import { useKeyboardHints } from '@/composables/useKeyboardHints'
import { useHotkeys } from '@/composables/useHotkeys'
import { captureTarget, sampleName } from '@/labels'
import UiText from '@/components/ui/UiText.vue'
import UiAlert from '@/components/ui/UiAlert.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
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
  tagsFor,
} from '@/components/settings/schemaForm'

const config = useConfigStore()
const toasts = useToastsStore()
const storage = useStorageStore()
const camera = useCameraStore()
const admin = useCameraAdminStore()
const { pref: layoutPref, setPref: setLayoutPref, isTouch } = useLayoutMode()
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
const DISPLAY_OWNED = ['timezone', 'kiosk.scale', 'kiosk.sleep_after_min']
const CAPTURE_OWNED = ['camera.keep_card_copy', 'camera.download_photos', 'camera.filename_prefix']
// Expert knobs live behind the Advanced disclosure.
const ADVANCED = [
  'camera.keepalive_enabled',
  'camera.keepalive_interval_s',
  'camera.connect_timeout_s',
  'camera.connect_retries',
  'camera.reconnect_interval_s',
  'camera.capture_timeout_s',
  'camera.event_quiet_window_s',
  'video.ffmpeg_path',
  'video.crf',
  'video.preset',
  'video.timeout_s',
  'liveview.jpeg_quality',
  'timelapse.failure_budget',
]
const sections = computed(() =>
  buildSections(config.schema).map((s) =>
    s.key === 'storage'
      ? { ...s, fields: s.fields.filter((f) => !STORAGE_OWNED.includes(f.name)) }
      : s,
  ),
)
const withFields = (s, keep) => ({ ...s, fields: s.fields.filter((f) => keep(s.path(f))) })
const shownSections = computed(() =>
  sections.value
    .map((s) =>
      withFields(
        s,
        (p) => !CAPTURE_OWNED.includes(p) && !DISPLAY_OWNED.includes(p) && !ADVANCED.includes(p),
      ),
    )
    .filter((s) => (s.fields.length || s.key === 'camera') && s.key !== 'storage'),
)
// The remaining storage fields (backup interval, verification) render inside the Storage card.
const storageSection = computed(() =>
  sections.value.find((s) => s.key === 'storage')
    ? withFields(
        sections.value.find((s) => s.key === 'storage'),
        () => true,
      )
    : null,
)
const advancedGroups = computed(() =>
  sections.value
    .map((s) => withFields(s, (p) => ADVANCED.includes(p)))
    .filter((s) => s.fields.length),
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
    nextTick(applyPending)
  } catch (e) {
    loadError.value = e?.message || 'Could not load settings'
  }
}
// One section is shown beside the list. The list is data-driven: an entry may bring its own
// component (API key today, Security later) and Advanced brings sub-tabs.
const root = ref(null)
const index = computed(() => [
  { id: 'display', label: 'Display' },
  { id: 'capture', label: 'Capture' },
  { id: 'storage', label: 'Storage' },
  ...shownSections.value.map((s) => ({ id: s.key, label: s.title })),
  ...(advancedGroups.value.length ? [{ id: 'advanced', label: 'Advanced' }] : []),
  { id: 'demo_camera', label: 'Demo camera' },
  { id: 'api-key', label: 'API key', component: ApiKeySection },
  { id: 'about', label: 'About', component: AboutSection },
])
const activeId = ref('display')
const current = computed(() => index.value.find((i) => i.id === activeId.value) || index.value[0])
const advTab = ref(null)
const advActive = computed(
  () =>
    advancedGroups.value.find((g) => g.key === advTab.value)?.key ?? advancedGroups.value[0]?.key,
)
function go(id, tab) {
  query.value = ''
  if (index.value.some((i) => i.id === id)) activeId.value = id
  if (tab) advTab.value = tab
}
// Deep link: #/settings?section=<id> opens that section.
let pendingSection = routeQuery.value.section || null
function applyPending() {
  if (!pendingSection || !index.value.some((i) => i.id === pendingSection)) return
  go(pendingSection)
  pendingSection = null
}
watch(
  () => routeQuery.value.section,
  (id) => {
    pendingSection = id || null
    nextTick(applyPending)
  },
)

// Search (desktop): filters the rows of every section; "/" focuses it.
const query = ref('')
const searchEl = ref(null)
const searching = computed(() => !isTouch.value && !!query.value.trim())
const hits = reactive(new Map())
provide(
  'settingsQuery',
  computed(() => (searching.value ? query.value.trim().toLowerCase() : '')),
)
provide('settingsHits', hits)
const noResults = computed(() => searching.value && ![...hits.values()].some(Boolean))
const show = (id) => searching.value || current.value.id === id
useHotkeys({
  '/': () => {
    if (!isTouch.value) searchEl.value?.focus()
  },
})
function onSaveKey(e) {
  if (isTouch.value || !(e.ctrlKey || e.metaKey) || String(e.key).toLowerCase() !== 's') return
  e.preventDefault()
  if (isDirty.value && !saving.value) save()
}
onMounted(() => document.addEventListener('keydown', onSaveKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onSaveKey))

// Which section owns a config path (for unsaved-change dots and jumping to an error).
function ownerOf(p) {
  if (DISPLAY_OWNED.includes(p)) return 'display'
  if (CAPTURE_OWNED.includes(p)) return 'capture'
  if (p === 'demo_camera') return 'demo_camera'
  if (ADVANCED.includes(p)) return 'advanced'
  const top = p.split('.')[0]
  return p.includes('.') && sections.value.some((s) => s.key === top) ? top : 'general'
}
const flagged = computed(() => new Set([...dirty.value, ...Object.keys(errors.value)].map(ownerOf)))
const flaggedTabs = computed(
  () =>
    new Set(
      [...dirty.value, ...Object.keys(errors.value)]
        .filter((p) => ownerOf(p) === 'advanced')
        .map((p) => p.split('.')[0]),
    ),
)
function showFirstError(fe) {
  const first = Object.keys(fe)[0]
  if (!first) return
  const id = ownerOf(first)
  go(id, id === 'advanced' ? first.split('.')[0] : undefined)
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
    if (Object.keys(fe).length) {
      toasts.error('Some settings are invalid. See the highlighted fields.')
      showFirstError(fe)
    } else toasts.error(e)
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
const kioskScale = computed(() => getPath(draft.value, 'kiosk.scale') || 'auto')
const setKioskScale = (v) => {
  setPath(draft.value, 'kiosk.scale', v)
  delete errors.value['kiosk.scale']
}
const kioskSleep = computed(() => getPath(draft.value, 'kiosk.sleep_after_min') ?? 5)
const setKioskSleep = (v) => {
  setPath(draft.value, 'kiosk.sleep_after_min', v == null ? 0 : Math.round(v))
  delete errors.value['kiosk.sleep_after_min']
}
const KIOSK_SCALES = [
  { value: 'auto', label: 'Auto' },
  { value: '1', label: '1×' },
  { value: '1.25', label: '1.25×' },
  { value: '1.5', label: '1.5×' },
  { value: '2', label: '2×' },
]
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
  <div ref="root" class="settings-layout">
    <nav
      v-if="config.config && sections.length"
      class="side"
      aria-label="Settings sections"
      data-test="section-index"
    >
      <label v-if="!isTouch" class="search">
        <svg
          aria-hidden="true"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-4-4" />
        </svg>
        <input
          ref="searchEl"
          v-model="query"
          type="search"
          placeholder="Search settings"
          aria-label="Search settings"
          data-test="search"
          @keydown.esc="query = ''"
        />
        <kbd v-if="!query">/</kbd>
      </label>
      <div class="side-list scroll-panel">
        <button
          v-for="i in index"
          :key="i.id"
          type="button"
          :data-chip="i.id"
          :aria-current="!searching && current.id === i.id ? 'true' : undefined"
          :class="{ on: !searching && current.id === i.id }"
          @click="go(i.id)"
        >
          {{ i.label }}
          <span
            v-if="flagged.has(i.id)"
            role="img"
            aria-label="Unsaved change"
            class="dot"
            data-test="nav-dot"
          />
        </button>
      </div>
    </nav>

    <div class="pane">
      <div class="pane-body scroll-panel" data-test="pane">
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
          <p v-if="noResults" class="py-6 text-sm text-camera-muted" data-test="no-results">
            No settings match "{{ query.trim() }}".
          </p>

          <SettingsSection v-if="show('display')" title="Display" data-section="display">
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
              title="Kiosk display scale"
              description="Size of the interface on the touchscreen kiosk only. Auto works it out from the screen."
              :tags="tagsFor('kiosk.scale')"
              :dirty="isFieldDirty('kiosk.scale')"
              :error="errors['kiosk.scale'] || ''"
              data-field="kiosk-scale"
            >
              <UiSegmented
                :model-value="kioskScale"
                :options="KIOSK_SCALES"
                aria-label="Kiosk display scale"
                data-test="kiosk-scale"
                @update:model-value="setKioskScale"
              />
            </SettingRow>
            <SettingRow
              title="Kiosk screen sleep"
              description="Turns the kiosk screen off after this many minutes without a touch. 0 keeps it on."
              :tags="tagsFor('kiosk.sleep_after_min')"
              :dirty="isFieldDirty('kiosk.sleep_after_min')"
              :error="errors['kiosk.sleep_after_min'] || ''"
              data-field="kiosk-sleep"
            >
              <UiNumber
                :model-value="kioskSleep"
                :min="0"
                :max="1440"
                :step="1"
                unit="min"
                data-test="kiosk-sleep"
                @update:model-value="setKioskSleep"
              />
            </SettingRow>
            <SettingRow
              v-if="!isTouch"
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

          <SettingsSection v-if="show('capture')" title="Capture" data-section="capture">
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
              title="Download to storage"
              description="Every photo is copied here, whichever option the camera uses."
            >
              <UiSelect
                :model-value="storage.targetId"
                :options="locationOptions"
                label="Download to storage"
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

          <StorageSection v-if="!searching && current.id === 'storage'" data-section="storage">
            <template v-if="storageSection?.fields.length" #extra>
              <SchemaField
                v-for="f in storageSection.fields"
                :key="storageSection.path(f)"
                :field="f"
                :model-value="value(storageSection, f)"
                :dirty="isFieldDirty(storageSection.path(f))"
                :error="errors[storageSection.path(f)] || ''"
                @update:model-value="setValue(storageSection, f, $event)"
              />
            </template>
          </StorageSection>
          <SettingsSection
            v-else-if="searching && storageSection?.fields.length"
            title="Storage"
            data-section="storage"
          >
            <SchemaField
              v-for="f in storageSection.fields"
              :key="storageSection.path(f)"
              :field="f"
              :model-value="value(storageSection, f)"
              :dirty="isFieldDirty(storageSection.path(f))"
              :error="errors[storageSection.path(f)] || ''"
              @update:model-value="setValue(storageSection, f, $event)"
            />
          </SettingsSection>

          <template v-for="s in shownSections" :key="s.key">
            <SettingsSection
              v-if="show(s.key)"
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
          </template>

          <template v-if="advancedGroups.length">
            <SettingsSection
              v-if="!searching && current.id === 'advanced'"
              title="Advanced"
              subtitle="Timeouts, keep-alive, ffmpeg and encoding"
              data-section="advanced"
              data-test="advanced"
            >
              <div class="tabs" role="tablist" aria-label="Advanced groups" data-test="adv-tabs">
                <button
                  v-for="g in advancedGroups"
                  :key="g.key"
                  type="button"
                  role="tab"
                  :aria-selected="advActive === g.key"
                  :class="{ on: advActive === g.key }"
                  :data-tab="g.key"
                  @click="advTab = g.key"
                >
                  {{ g.title }}
                  <span
                    v-if="flaggedTabs.has(g.key)"
                    role="img"
                    aria-label="Unsaved change"
                    class="dot"
                  />
                </button>
              </div>
              <template v-for="g in advancedGroups" :key="g.key">
                <div v-if="advActive === g.key" role="tabpanel">
                  <SchemaField
                    v-for="f in g.fields"
                    :key="g.path(f)"
                    :field="f"
                    :model-value="value(g, f)"
                    :dirty="isFieldDirty(g.path(f))"
                    :error="errors[g.path(f)] || ''"
                    @update:model-value="setValue(g, f, $event)"
                  />
                </div>
              </template>
            </SettingsSection>
            <template v-else-if="searching">
              <SettingsSection
                v-for="g in advancedGroups"
                :key="g.key"
                :title="`Advanced › ${g.title}`"
                data-section="advanced"
              >
                <SchemaField
                  v-for="f in g.fields"
                  :key="g.path(f)"
                  :field="f"
                  :model-value="value(g, f)"
                  :dirty="isFieldDirty(g.path(f))"
                  :error="errors[g.path(f)] || ''"
                  @update:model-value="setValue(g, f, $event)"
                />
              </SettingsSection>
            </template>
          </template>

          <DemoCameraSection
            v-if="show('demo_camera')"
            :model-value="!!draft.demo_camera"
            :dirty="isFieldDirty('demo_camera')"
            @update:model-value="draft.demo_camera = $event"
          />

          <component
            :is="current.component"
            v-if="!searching && current.component"
            :data-section="current.id"
          />

          <UiAlert
            v-if="config.resetChanged?.length"
            tone="info"
            title="Reset changed"
            data-test="reset-changed"
          >
            {{ titled(config.resetChanged) }}
          </UiAlert>
        </template>
        <p v-else class="text-sm text-camera-muted" aria-live="polite">Loading settings…</p>
      </div>

      <footer v-if="config.config && sections.length" class="pane-foot">
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
        <span class="foot-note">
          <span
            v-if="isDirty"
            class="whitespace-nowrap tabular-nums text-camera-text"
            aria-live="polite"
            data-test="savebar"
            >{{ dirty.length }} unsaved change{{ dirty.length === 1 ? '' : 's' }}</span
          >
          <span v-else-if="!isTouch"
            >Restores every setting, including the demo camera switch.</span
          >
          <span v-if="isDirty && !isTouch"> · kept while you switch sections</span>
        </span>
        <UiButton
          variant="ghost"
          size="sm"
          :disabled="saving || !isDirty"
          data-test="discard"
          @click="discard"
        >
          Discard
        </UiButton>
        <UiButton
          variant="primary"
          size="sm"
          :loading="saving"
          :disabled="!isDirty"
          :title="isTouch ? undefined : 'Save (Ctrl+S)'"
          data-test="save"
          @click="save"
        >
          Save changes
        </UiButton>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.settings-layout {
  height: 100%;
  min-height: 0;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 16px;
}
.side {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.card');
  background: theme('colors.camera.surface');
}
html[data-layout='touch'] .side {
  padding: 8px;
}
.side-list {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.side-list button {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: var(--ctl-sm);
  padding: 0 12px;
  border-radius: theme('borderRadius.control');
  color: theme('colors.camera.muted');
  text-align: left;
}
.side-list button:hover {
  background: theme('colors.camera.hover');
  color: theme('colors.camera.text');
}
.side-list button.on {
  background: theme('colors.camera.raised');
  color: theme('colors.camera.text');
  box-shadow: inset 3px 0 0 theme('colors.camera.accent');
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: theme('colors.camera.accent');
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 10px;
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.control');
  background: theme('colors.camera.bg');
  color: theme('colors.camera.muted');
}
.search input {
  all: unset;
  flex: 1;
  min-width: 0;
  width: 0;
  font-size: 13px;
  color: theme('colors.camera.text');
}
.pane {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid theme('colors.camera.border');
  border-radius: theme('borderRadius.card');
  background: theme('colors.camera.surface');
}
.pane:only-child {
  grid-column: 1 / -1;
}
.pane-body {
  position: relative; /* contains sr-only inputs so they cannot extend the document */
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 6px 28px 12px;
}
/* Whole-card sections (Storage, API key, About) sit flat inside the pane. */
.pane-body > :deep(section.rounded-card) {
  border: 0;
  background: none;
}
.pane-body > :deep(section.rounded-card > .p-4),
.pane-body > :deep(section.rounded-card > header) {
  padding-inline: 0;
}
.pane-foot {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 28px;
  border-top: 1px solid theme('colors.camera.subtle');
}
.foot-note {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: theme('colors.camera.muted');
}
.tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 4px;
  border-bottom: 1px solid theme('colors.camera.subtle');
  overflow-x: auto;
}
.tabs button {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: var(--ctl-sm);
  padding: 0 14px;
  color: theme('colors.camera.muted');
  white-space: nowrap;
}
.tabs button.on {
  color: theme('colors.camera.text');
  box-shadow: inset 0 -2px 0 theme('colors.camera.accent');
}
@media (max-width: 719px) {
  .settings-layout {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    gap: 8px;
  }
  .side {
    padding: 6px;
  }
  .side-list {
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .side-list button {
    gap: 8px;
  }
  .pane-body {
    padding-inline: 14px;
  }
  .pane-foot {
    padding-inline: 14px;
    flex-wrap: wrap;
  }
  .foot-note {
    display: none;
  }
}
</style>
