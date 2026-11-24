<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import UiCard from '@/components/ui/UiCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import SchemaField from '@/components/settings/SchemaField.vue'
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
} from '@/components/settings/schemaForm'

const config = useConfigStore()
const toasts = useToastsStore()

const draft = ref({})
let base = {} // server config the draft was last synced to
const errors = ref({})
const saving = ref(false)
const resetting = ref(false)
const loadError = ref('')

// Storage locations/target/backups are managed by StorageSection, not the generic form.
const STORAGE_OWNED = ['locations', 'target_id', 'backup_ids']
const sections = computed(() =>
  buildSections(config.schema).map((s) =>
    s.key === 'storage'
      ? { ...s, fields: s.fields.filter((f) => !STORAGE_OWNED.includes(f.name)) }
      : s,
  ),
)
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
onMounted(load)

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
</script>

<template>
  <div class="mx-auto flex max-w-3xl flex-col gap-4">
    <h2 class="text-xl font-semibold">Settings</h2>

    <div
      v-if="config.restartRequired.length"
      role="status"
      class="rounded-lg border border-yellow-500/50 bg-yellow-500/10 p-3 text-sm"
      data-test="restart"
    >
      <div class="flex flex-wrap items-center gap-2">
        <span>
          Restart required for: <strong>{{ config.restartRequired.join(', ') }}</strong>
        </span>
        <UiButton
          class="ml-auto"
          size="sm"
          variant="ghost"
          data-test="dismiss-restart"
          @click="config.dismissRestart()"
        >
          Dismiss
        </UiButton>
      </div>
    </div>

    <UiEmpty v-if="loadError" title="Settings could not be loaded" :hint="loadError">
      <template #actions><UiButton variant="primary" @click="load">Retry</UiButton></template>
    </UiEmpty>

    <template v-else-if="config.config && sections.length">
      <ApiKeySection />
      <StorageSection />
      <DemoCameraSection
        :model-value="!!draft.demo_camera"
        :dirty="isFieldDirty('demo_camera')"
        @update:model-value="draft.demo_camera = $event"
      />
      <UiCard
        v-for="s in sections"
        :key="s.key"
        :title="s.title"
        :subtitle="s.description"
        :data-section="s.key"
      >
        <div class="grid gap-4 sm:grid-cols-2">
          <SchemaField
            v-for="f in s.fields"
            :key="s.path(f)"
            :field="f"
            :model-value="value(s, f)"
            :dirty="isFieldDirty(s.path(f))"
            :error="errors[s.path(f)] || ''"
            :class="f.kind === 'strings' ? 'sm:col-span-2' : ''"
            @update:model-value="setValue(s, f, $event)"
          />
        </div>
      </UiCard>

      <p
        v-if="config.resetChanged?.length"
        role="status"
        class="rounded-lg border border-camera-border bg-camera-surface p-3 text-sm"
        data-test="reset-changed"
      >
        Reset changed: <strong>{{ config.resetChanged.join(', ') }}</strong>
      </p>

      <div
        class="sticky bottom-0 flex flex-wrap items-center gap-2 rounded-lg border border-camera-border bg-camera-surface p-3"
      >
        <UiButton
          variant="primary"
          :loading="saving"
          :disabled="!isDirty"
          data-test="save"
          @click="save"
        >
          Save changes
        </UiButton>
        <UiButton
          variant="ghost"
          :disabled="!isDirty || saving"
          data-test="discard"
          @click="discard"
        >
          Discard
        </UiButton>
        <span v-if="isDirty" class="text-xs text-camera-muted" aria-live="polite">
          {{ dirty.length }} unsaved change{{ dirty.length === 1 ? '' : 's' }}
        </span>
        <UiConfirmButton
          class="ml-auto"
          variant="danger"
          confirm-text="Reset all, incl. demo camera?"
          :loading="resetting"
          data-test="reset"
          @confirm="resetDefaults"
        >
          Reset to defaults
        </UiConfirmButton>
        <p class="basis-full text-xs text-camera-muted">
          Reset restores every setting, including the demo camera switch.
        </p>
      </div>
    </template>
    <p v-else class="text-sm text-camera-muted" aria-live="polite">Loading settings...</p>

    <AboutSection />
  </div>
</template>
