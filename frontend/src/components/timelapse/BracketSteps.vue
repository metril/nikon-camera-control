<script setup>
import { ref, computed, onMounted } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiText from '@/components/ui/UiText.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import { useSettingsStore } from '@/stores/settings'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import { draft } from './useDraft'
import { newStep, newRow, bracketTypes } from './bracketUtils'

const MIN = 2
const MAX = 15
const settings = useSettingsStore()
const camera = useCameraStore()
const toasts = useToastsStore()
const steps = computed(() => draft.bracket.steps)
const expanded = ref(new Set()) // step ids, never indices

const settingList = computed(() => {
  const seen = new Map()
  for (const s of [...settings.common, ...settings.all])
    if (!s.readonly && s.writable && s.choices?.length) seen.set(s.name, s)
  if (!seen.size) return bracketTypes.map((t) => ({ name: t.setting, label: t.label, choices: [] }))
  return [...seen.values()]
})
const settingOptions = computed(() =>
  settingList.value.map((s) => ({ value: s.name, label: s.label || s.name })),
)
const choicesOf = (name) => settingList.value.find((s) => s.name === name)?.choices ?? []
const valueOptions = (name) => choicesOf(name).map((v) => ({ value: v, label: v }))

onMounted(() => {
  if (camera.connected && !settings.all.length) settings.fetchAll().catch((e) => toasts.error(e))
})

function toggle(id) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}
function add() {
  if (steps.value.length >= MAX) return
  const s = newStep()
  steps.value.push(s)
  toggle(s.id)
}
function remove(id) {
  if (steps.value.length <= MIN) return
  draft.bracket.steps = steps.value.filter((s) => s.id !== id)
  const next = new Set(expanded.value)
  next.delete(id)
  expanded.value = next
}
function move(i, d) {
  const j = i + d
  if (j < 0 || j >= steps.value.length) return
  const arr = [...steps.value]
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  draft.bracket.steps = arr
}
const setDelay = (s, v) => (s.delay_ms = v == null ? 0 : Math.round(v))
</script>

<template>
  <div class="space-y-2">
    <ol class="space-y-2">
      <li
        v-for="(s, i) in steps"
        :key="s.id"
        class="rounded-lg border border-slate-700 bg-slate-800/50 p-2"
        data-test="step"
      >
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="flex-1 truncate rounded px-1 text-left text-sm focus-visible:outline focus-visible:outline-2"
            :aria-expanded="expanded.has(s.id)"
            @click="toggle(s.id)"
          >
            {{ i + 1 }}. {{ s.label || 'Step' }}
            <span class="text-xs text-slate-400">
              {{
                s.rows
                  .filter((r) => r.name)
                  .map((r) => `${r.name}=${r.value}`)
                  .join(', ')
              }}
            </span>
          </button>
          <UiButton
            size="sm"
            variant="ghost"
            aria-label="Move step up"
            :disabled="i === 0"
            @click="move(i, -1)"
            >▲</UiButton
          >
          <UiButton
            size="sm"
            variant="ghost"
            aria-label="Move step down"
            :disabled="i === steps.length - 1"
            @click="move(i, 1)"
            >▼</UiButton
          >
          <UiButton
            size="sm"
            variant="ghost"
            aria-label="Remove step"
            :disabled="steps.length <= MIN"
            @click="remove(s.id)"
            >×</UiButton
          >
        </div>
        <div v-if="expanded.has(s.id)" class="mt-2 space-y-2" data-test="step-detail">
          <div class="grid gap-2 sm:grid-cols-2">
            <UiText v-model="s.label" label="Label" :maxlength="80" />
            <UiNumber
              :model-value="s.delay_ms"
              label="Delay before shot"
              unit="ms"
              :min="0"
              :max="60000"
              @update:model-value="(v) => setDelay(s, v)"
            />
          </div>
          <div v-for="r in s.rows" :key="r.id" class="flex flex-wrap items-end gap-2">
            <UiSelect
              v-model="r.name"
              label="Setting"
              :options="settingOptions"
              @update:model-value="r.value = ''"
            />
            <UiSelect
              v-if="choicesOf(r.name).length"
              v-model="r.value"
              label="Value"
              :options="valueOptions(r.name)"
            />
            <UiText v-else v-model="r.value" label="Value" />
            <UiButton
              size="sm"
              variant="ghost"
              aria-label="Remove setting"
              :disabled="s.rows.length <= 1"
              @click="s.rows = s.rows.filter((x) => x.id !== r.id)"
            >
              ×
            </UiButton>
          </div>
          <UiButton size="sm" @click="s.rows.push(newRow())">Add setting</UiButton>
        </div>
      </li>
    </ol>
    <div class="flex items-center gap-3">
      <UiButton :disabled="steps.length >= MAX" @click="add">Add step</UiButton>
      <span class="text-xs text-slate-400">{{ steps.length }} of {{ MIN }} to {{ MAX }} steps</span>
    </div>
  </div>
</template>
