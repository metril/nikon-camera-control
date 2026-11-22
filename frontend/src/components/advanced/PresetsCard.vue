<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'
import { useToastsStore } from '@/stores/toasts'
import { downloadBlob } from '@/api'
import AdvCard from './AdvCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiBadge from '@/components/ui/UiBadge.vue'

const emit = defineEmits(['navigate'])
const presets = usePresetsStore()
const settings = useSettingsStore()
const toasts = useToastsStore()

const settingsPresets = computed(() => presets.items.filter((p) => p.kind === 'settings'))
const bracketPresets = computed(() => presets.items.filter((p) => p.kind === 'bracket'))

// --- apply
const applying = ref(null)
const results = reactive({}) // id -> { ok, applied?, error?, invalid?, nearby? }
async function apply(p) {
  applying.value = p.id
  try {
    const r = await presets.apply(p.id)
    results[p.id] = { ok: true, applied: r.applied || [] }
  } catch (e) {
    const d = e?.details || {}
    results[p.id] = {
      ok: false,
      error: e?.message || 'Apply failed',
      invalid: d.failed || d.name || null,
      value: d.value,
      nearby: Array.isArray(d.nearby) ? d.nearby : [],
      applied: Array.isArray(d.applied) ? d.applied : [],
    }
  } finally {
    applying.value = null
  }
}

// --- save from camera
const writable = computed(() => settings.common.filter((s) => s.writable && !s.readonly))
const saveOpen = ref(false)
const save = reactive({ name: '', description: '', names: [] })
const saving = ref(false)
async function openSave() {
  if (!settings.common.length) await settings.fetchCommon().catch((e) => toasts.error(e))
  save.name = ''
  save.description = ''
  save.names = writable.value.map((s) => s.name)
  saveOpen.value = true
}
const toggleName = (n) =>
  (save.names = save.names.includes(n) ? save.names.filter((x) => x !== n) : [...save.names, n])
const saveValid = computed(() => save.name.trim() && save.names.length)
async function doSave() {
  saving.value = true
  try {
    await presets.fromCamera({
      name: save.name.trim(),
      description: save.description.trim(),
      names: save.names,
    })
    saveOpen.value = false
    toasts.success('Preset saved')
  } catch (e) {
    toasts.error(e)
  } finally {
    saving.value = false
  }
}

// --- edit
const edit = reactive({ open: false, preset: null, name: '', description: '', saving: false })
function openEdit(p) {
  Object.assign(edit, { open: true, preset: p, name: p.name, description: p.description || '' })
}
async function doEdit() {
  edit.saving = true
  try {
    const p = edit.preset
    await presets.update(p.id, {
      kind: 'settings',
      name: edit.name.trim(),
      description: edit.description.trim(),
      values: p.values,
    })
    edit.open = false
  } catch (e) {
    toasts.error(e)
  } finally {
    edit.saving = false
  }
}

async function remove(p) {
  try {
    await presets.remove(p.id)
    delete results[p.id]
  } catch (e) {
    toasts.error(e)
  }
}

// --- export / import
const exporting = ref(false)
async function doExport() {
  exporting.value = true
  try {
    const doc = await presets.exportAll()
    downloadBlob(
      new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }),
      'presets.json',
    )
  } catch (e) {
    toasts.error(e)
  } finally {
    exporting.value = false
  }
}
const replace = ref(false)
const importing = ref(false)
const importResult = ref(null)
const fileInput = ref(null)
async function onFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  importing.value = true
  importResult.value = null
  try {
    let doc
    try {
      doc = JSON.parse(await file.text())
    } catch {
      throw new Error('That file is not valid JSON')
    }
    const list = Array.isArray(doc) ? doc : doc?.presets
    if (!Array.isArray(list)) throw new Error('No "presets" list found in the file')
    importResult.value = await presets.importPresets({
      schema_version: doc.schema_version ?? 1,
      replace: replace.value,
      presets: list,
    })
  } catch (e) {
    toasts.error(e)
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  presets.fetch().catch(() => {})
  if (!settings.common.length) settings.fetchCommon().catch(() => {})
})
</script>

<template>
  <AdvCard title="Settings presets" subtitle="Save and re-apply camera settings">
    <template #default="{ disabled, reason }">
      <p v-if="presets.warning" class="text-sm text-amber-300">{{ presets.warning }}</p>
      <ul v-if="settingsPresets.length" class="space-y-3" data-testid="settings-presets">
        <li v-for="p in settingsPresets" :key="p.id" class="rounded border border-slate-700 p-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="min-w-0">
              <p class="font-medium">
                {{ p.name }}
                <UiBadge v-if="p.builtin" tone="neutral">built-in</UiBadge>
              </p>
              <p v-if="p.description" class="text-sm text-slate-400">{{ p.description }}</p>
              <p class="text-xs text-slate-400">
                {{ Object.keys(p.values || {}).length }} settings
              </p>
            </div>
            <div class="flex flex-wrap gap-1">
              <UiButton
                size="sm"
                variant="primary"
                :loading="applying === p.id"
                :disabled="disabled"
                :title="reason"
                @click="apply(p)"
              >
                Apply
              </UiButton>
              <UiButton
                v-if="!p.builtin"
                size="sm"
                :aria-label="`Edit ${p.name}`"
                @click="openEdit(p)"
                >Edit</UiButton
              >
              <UiConfirmButton
                v-if="!p.builtin"
                size="sm"
                variant="danger"
                :aria-label="`Delete ${p.name}`"
                @confirm="remove(p)"
              >
                Delete
              </UiConfirmButton>
            </div>
          </div>
          <div
            v-if="results[p.id]"
            class="mt-2 text-sm"
            aria-live="polite"
            :data-testid="`result-${p.id}`"
          >
            <template v-if="results[p.id].ok">
              <p class="text-emerald-400">Applied:</p>
              <ul>
                <li v-for="a in results[p.id].applied" :key="a.name">
                  {{ a.name }} = {{ a.value }}
                </li>
              </ul>
            </template>
            <template v-else>
              <p class="text-red-400" role="alert">
                Nothing was applied: {{ results[p.id].error }}
              </p>
              <p v-if="results[p.id].invalid" class="text-red-300">
                Invalid setting: <strong>{{ results[p.id].invalid }}</strong>
                <span v-if="results[p.id].value !== undefined">
                  (value {{ results[p.id].value }})</span
                >
              </p>
              <p v-if="results[p.id].nearby.length" class="text-slate-400">
                Closest choices: {{ results[p.id].nearby.join(', ') }}
              </p>
              <p v-if="results[p.id].applied.length" class="text-amber-300">
                Already applied before the failure: {{ results[p.id].applied.join(', ') }}
              </p>
            </template>
          </div>
        </li>
      </ul>
      <p v-else class="text-sm text-slate-400">No settings presets yet.</p>

      <div class="flex flex-wrap gap-2">
        <UiButton variant="primary" :disabled="disabled" :title="reason" @click="openSave"
          >Save current settings as preset</UiButton
        >
        <UiButton :loading="exporting" @click="doExport">Export</UiButton>
        <UiButton :loading="importing" @click="fileInput.click()">Import…</UiButton>
        <input
          ref="fileInput"
          type="file"
          accept="application/json,.json"
          class="hidden"
          aria-label="Import presets file"
          data-testid="import-file"
          @change="onFile"
        />
      </div>
      <UiToggle v-model="replace" label="Import replaces existing presets" />

      <div v-if="importResult" class="text-sm" aria-live="polite" data-testid="import-result">
        <p>
          {{ importResult.created }} created, {{ importResult.skipped }} skipped,
          {{ importResult.failed }} failed
        </p>
        <ul>
          <li v-for="i in importResult.items" :key="i.index">
            <UiBadge
              :tone="i.status === 'created' ? 'ok' : i.status === 'skipped' ? 'warn' : 'error'"
              >{{ i.status }}</UiBadge
            >
            {{ i.name || `#${i.index + 1}` }}
            <span v-if="i.error" class="text-red-300">{{ i.error }}</span>
          </li>
        </ul>
      </div>

      <div
        v-if="bracketPresets.length"
        class="space-y-1 border-t border-slate-700 pt-2"
        data-testid="bracket-presets"
      >
        <p class="text-sm font-medium">Bracket presets (read-only here)</p>
        <ul class="text-sm text-slate-300">
          <li v-for="p in bracketPresets" :key="p.id">
            {{ p.name
            }}<span v-if="p.description" class="text-slate-400"> – {{ p.description }}</span>
          </li>
        </ul>
        <button
          type="button"
          class="text-sm text-sky-400 underline"
          @click="emit('navigate', 'timelapse')"
        >
          Edit bracket presets in the Time-lapse tab
        </button>
      </div>

      <UiModal :open="saveOpen" title="Save current settings as preset" @close="saveOpen = false">
        <div class="space-y-3">
          <UiText v-model="save.name" label="Name" :maxlength="80" />
          <UiText v-model="save.description" label="Description" :maxlength="500" />
          <fieldset>
            <legend class="mb-1 text-sm">Settings to include</legend>
            <div class="grid grid-cols-1 gap-1 sm:grid-cols-2">
              <label v-for="s in writable" :key="s.name" class="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  :checked="save.names.includes(s.name)"
                  @change="toggleName(s.name)"
                />
                {{ s.label || s.name }} <span class="text-slate-400">{{ s.value }}</span>
              </label>
            </div>
          </fieldset>
        </div>
        <template #footer>
          <UiButton @click="saveOpen = false">Cancel</UiButton>
          <UiButton variant="primary" :loading="saving" :disabled="!saveValid" @click="doSave"
            >Save preset</UiButton
          >
        </template>
      </UiModal>

      <UiModal :open="edit.open" title="Edit preset" @close="edit.open = false">
        <div class="space-y-3">
          <UiText v-model="edit.name" label="Name" :maxlength="80" />
          <UiText v-model="edit.description" label="Description" :maxlength="500" />
        </div>
        <template #footer>
          <UiButton @click="edit.open = false">Cancel</UiButton>
          <UiButton
            variant="primary"
            :loading="edit.saving"
            :disabled="!edit.name.trim()"
            @click="doEdit"
            >Save</UiButton
          >
        </template>
      </UiModal>
    </template>
  </AdvCard>
</template>
