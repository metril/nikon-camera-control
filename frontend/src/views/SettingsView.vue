<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'
import { useCameraStore } from '@/stores/camera'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useLayoutMode } from '@/composables/useLayoutMode'
import { routeQuery } from '@/components/shell/useTabs'
import { useKeyboardHints } from '@/composables/useKeyboardHints'
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
const advancedOpen = ref(false)
const advancedBad = computed(() =>
  advancedGroups.value.some((g) =>
    g.fields.some((f) => isFieldDirty(g.path(f)) || errors.value[g.path(f)]),
  ),
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
    nextTick(scrollToSection)
  } catch (e) {
    loadError.value = e?.message || 'Could not load settings'
  }
}
// Deep link: #/settings?section=<id> scrolls to that section once it is rendered.
const root = ref(null)
let pendingSection = routeQuery.value.section || null
function scrollToSection() {
  if (!pendingSection) return
  const el = root.value?.querySelector(`[data-section="${CSS.escape(pendingSection)}"]`)
  if (!el) return
  if (pendingSection === 'advanced') advancedOpen.value = true
  pendingSection = null
  el.scrollIntoView({ block: 'start' })
}
watch(
  () => routeQuery.value.section,
  (id) => {
    pendingSection = id || null
    nextTick(scrollToSection)
  },
)
const goSection = (id) => {
  pendingSection = id
  scrollToSection()
  chipsEl.value
    ?.querySelector(`[data-chip="${CSS.escape(id)}"]`)
    ?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
}
// Narrow screens scroll the chip row: fade whichever edge has more chips behind it.
const chipsEl = ref(null)
const fadeL = ref(false)
const fadeR = ref(false)
const fadeT = ref(false)
const fadeB = ref(false)
function updateFade() {
  const e = chipsEl.value
  if (!e) return
  fadeL.value = e.scrollLeft > 2
  fadeR.value = e.scrollLeft + e.clientWidth < e.scrollWidth - 2
  // wide screens: the list is a column that scrolls vertically
  fadeT.value = e.scrollTop > 2
  fadeB.value = e.scrollTop + e.clientHeight < e.scrollHeight - 2
}
onMounted(() => {
  window.addEventListener('resize', updateFade)
  nextTick(updateFade)
})
onBeforeUnmount(() => window.removeEventListener('resize', updateFade))
const index = computed(() => [
  { id: 'display', label: 'Display' },
  { id: 'capture', label: 'Capture' },
  { id: 'storage', label: 'Storage' },
  ...shownSections.value.map((s) => ({ id: s.key, label: s.title })),
  ...(advancedGroups.value.length ? [{ id: 'advanced', label: 'Advanced' }] : []),
  { id: 'demo_camera', label: 'Demo camera' },
  { id: 'api-key', label: 'API key' },
  { id: 'about', label: 'About' },
])
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
  <!-- Wide screens: section list in a sticky left column; narrow: a scrolling chip row -->
  <div ref="root" class="settings-layout">
    <h2 class="text-xl font-semibold">Settings</h2>

    <nav
      v-if="config.config && sections.length"
      ref="chipsEl"
      class="chips"
      :class="{ 'fade-l': fadeL, 'fade-r': fadeR, 'fade-t': fadeT, 'fade-b': fadeB }"
      aria-label="Settings sections"
      data-test="section-index"
      @scroll.passive="updateFade"
    >
      <button
        v-for="i in index"
        :key="i.id"
        type="button"
        :data-chip="i.id"
        @click="goSection(i.id)"
      >
        {{ i.label }}
      </button>
    </nav>

    <div class="settings-main">
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
            title="Kiosk display scale"
            description="Size of the interface on the touchscreen kiosk only. Auto works it out from the screen."
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

        <StorageSection data-section="storage">
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

        <details
          v-if="advancedGroups.length"
          class="adv rounded-card border border-camera-border bg-camera-surface"
          data-section="advanced"
          data-test="advanced"
          :open="advancedOpen || advancedBad"
          @toggle="advancedOpen = $event.target.open"
        >
          <summary class="adv-sum">
            <span class="text-sm font-semibold">Advanced</span>
            <span class="text-xs text-camera-muted">Timeouts, keep-alive, ffmpeg and encoding</span>
          </summary>
          <div class="grid gap-5 px-4 pb-4">
            <section v-for="g in advancedGroups" :key="g.key">
              <h3 class="eyebrow mb-2">{{ g.title }}</h3>
              <SchemaField
                v-for="f in g.fields"
                :key="g.path(f)"
                :field="f"
                :model-value="value(g, f)"
                :dirty="isFieldDirty(g.path(f))"
                :error="errors[g.path(f)] || ''"
                @update:model-value="setValue(g, f, $event)"
              />
            </section>
          </div>
        </details>

        <DemoCameraSection
          :model-value="!!draft.demo_camera"
          :dirty="isFieldDirty('demo_camera')"
          @update:model-value="draft.demo_camera = $event"
        />
        <ApiKeySection data-section="api-key" />

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

      <AboutSection data-section="about" />

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
  </div>
</template>

<style scoped>
.settings-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-inline: auto;
  max-width: 760px;
}
.settings-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.chips.fade-r {
  mask-image: linear-gradient(to right, #000 calc(100% - 40px), transparent);
}
.chips.fade-l {
  mask-image: linear-gradient(to right, transparent, #000 40px);
}
.chips.fade-l.fade-r {
  mask-image: linear-gradient(
    to right,
    transparent,
    #000 40px,
    #000 calc(100% - 40px),
    transparent
  );
}
/* Wide screens: every section visible in a sticky left column */
@media (min-width: 1000px) {
  .settings-layout {
    display: grid;
    grid-template-columns: 168px minmax(0, 760px);
    grid-template-rows: auto 1fr;
    gap: 16px 24px;
    max-width: calc(168px + 24px + 760px);
    align-items: start;
  }
  .settings-layout > h2 {
    grid-column: 2;
    grid-row: 1;
  }
  .settings-layout > .settings-main {
    grid-column: 2;
    grid-row: 2;
  }
  .settings-layout > .chips {
    grid-column: 1;
    grid-row: 1 / span 2;
    /* the list scrolls on its own when taller than the screen (13 sections on a 600 px kiosk) */
    max-height: calc(100dvh - 59px - var(--nav, 0px) - 16px);
    overflow-x: hidden;
    overflow-y: auto;
    flex-direction: column;
    gap: 2px;
    margin: 0;
    padding: 0;
    border: 0;
    box-shadow: none;
    background: none;
    mask-image: none;
  }
  .settings-layout > .chips button {
    height: auto;
    min-height: var(--ctl-sm);
    padding: 0 12px;
    border: 0;
    border-radius: theme('borderRadius.control');
    background: none;
    color: theme('colors.camera.muted');
    text-align: left;
  }
  .settings-layout > .chips.fade-b {
    mask-image: linear-gradient(to bottom, #000 calc(100% - 40px), transparent);
  }
  .settings-layout > .chips.fade-t {
    mask-image: linear-gradient(to bottom, transparent, #000 40px);
  }
  .settings-layout > .chips.fade-t.fade-b {
    mask-image: linear-gradient(
      to bottom,
      transparent,
      #000 40px,
      #000 calc(100% - 40px),
      transparent
    );
  }
  .settings-layout > .chips button:hover {
    background: theme('colors.camera.hover');
    color: theme('colors.camera.text');
  }
}
.chips {
  position: sticky;
  top: calc(env(safe-area-inset-top, 0px) + 59px);
  z-index: 14;
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scrollbar-width: none;
  margin-inline: -16px;
  padding: 8px 16px;
  background: theme('colors.camera.bg');
  /* cover the gap above the chips so scrolled content never peeks out under the header */
  box-shadow: 0 -12px 0 0 theme('colors.camera.bg');
  border-bottom: 1px solid theme('colors.camera.subtle');
}
html[data-layout='touch'] .chips {
  top: calc(env(safe-area-inset-top, 0px) + 63px);
}
.chips button {
  flex: none;
  height: var(--ctl-sm);
  padding: 0 12px;
  border: 1px solid theme('colors.camera.border');
  border-radius: 9999px;
  background: theme('colors.camera.raised');
  color: theme('colors.camera.text');
  font-size: 13px;
  white-space: nowrap;
}
.chips button:active {
  background: theme('colors.camera.hover');
}
[data-section] {
  scroll-margin-top: 120px;
}
.adv-sum {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  min-height: var(--ctl);
  padding: 12px 16px;
  cursor: pointer;
}
</style>
