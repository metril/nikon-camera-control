<script setup>
import { computed, onMounted, watch } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiText from '@/components/ui/UiText.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import { useSettingsStore } from '@/stores/settings'
import { useCameraStore } from '@/stores/camera'
import { useToastsStore } from '@/stores/toasts'
import { settingName } from '@/labels'
import { draft } from './useDraft'
import { newStep, newRow, bracketTypes } from './bracketUtils'

const MIN = 2
const MAX = 15
const MAX_ROWS = 4
defineProps({ disabled: Boolean })
const settings = useSettingsStore()
const camera = useCameraStore()
const toasts = useToastsStore()
const steps = computed(() => draft.bracket.steps)

const settingList = computed(() => {
  const seen = new Map()
  for (const s of [...settings.common, ...settings.all])
    if (!s.readonly && s.writable && s.choices?.length) seen.set(s.name, s)
  if (!seen.size) return bracketTypes.map((t) => ({ name: t.setting, label: t.label, choices: [] }))
  return [...seen.values()]
})
const settingOptions = computed(() =>
  settingList.value.map((s) => ({ value: s.name, label: settingName(s.label || s.name) })),
)
const choicesOf = (name) => settingList.value.find((s) => s.name === name)?.choices ?? []
const valueOptions = (name) => choicesOf(name).map((v) => ({ value: v, label: v }))

onMounted(() => {
  if (camera.connected && !settings.all.length) settings.fetchAll().catch((e) => toasts.error(e))
})

// The camera's valid values arrive once it is connected (it may connect after this opens).
watch(
  () => camera.connected,
  (on) => on && !settings.all.length && settings.fetchAll().catch((e) => toasts.error(e)),
)

const add = () => steps.value.length < MAX && steps.value.push(newStep())
function remove(id) {
  if (steps.value.length <= MIN) return
  draft.bracket.steps = steps.value.filter((s) => s.id !== id)
}
function move(i, d) {
  const j = i + d
  if (j < 0 || j >= steps.value.length) return
  const arr = [...steps.value]
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  draft.bracket.steps = arr
}
/** The API stores the delay in milliseconds; the field is in seconds. */
const delayS = (s) => s.delay_ms / 1000
const setDelay = (s, v) => (s.delay_ms = v == null ? 0 : Math.round(v * 1000))
</script>

<template>
  <div class="grid gap-3">
    <div
      v-for="(s, i) in steps"
      :key="s.id"
      class="grid gap-3 rounded-inner border border-camera-subtle bg-camera-bg p-3"
      data-test="step"
    >
      <div class="flex items-center justify-between gap-2">
        <b class="text-sm">Step {{ i + 1 }}</b>
        <div class="flex gap-0.5">
          <UiButton
            size="sm"
            variant="ghost"
            class="!w-[var(--ctl-sm)] !px-0"
            :aria-label="`Move step ${i + 1} up`"
            :disabled="disabled || i === 0"
            @click="move(i, -1)"
          >
            <UiIcon name="ChevronUp" />
          </UiButton>
          <UiButton
            size="sm"
            variant="ghost"
            class="!w-[var(--ctl-sm)] !px-0"
            :aria-label="`Move step ${i + 1} down`"
            :disabled="disabled || i === steps.length - 1"
            @click="move(i, 1)"
          >
            <UiIcon name="ChevronDown" />
          </UiButton>
          <UiButton
            size="sm"
            variant="ghost"
            class="!w-[var(--ctl-sm)] !px-0"
            :aria-label="`Remove step ${i + 1}`"
            :disabled="disabled || steps.length <= MIN"
            @click="remove(s.id)"
          >
            <UiIcon name="Trash2" />
          </UiButton>
        </div>
      </div>
      <div class="step-grid">
        <UiText
          v-model="s.label"
          label="Label"
          placeholder="Optional"
          :maxlength="80"
          :disabled="disabled"
        />
        <UiNumber
          :model-value="delayS(s)"
          label="Delay before shot"
          unit="s"
          :min="0"
          :max="60"
          :step="0.1"
          :disabled="disabled"
          @update:model-value="(v) => setDelay(s, v)"
        />
        <span aria-hidden="true" />
      </div>
      <div class="grid gap-2">
        <span class="text-xs font-medium text-camera-muted">Settings for this shot</span>
        <div v-for="r in s.rows" :key="r.id" class="step-grid" data-test="setting-row">
          <UiSelect
            v-model="r.name"
            :options="settingOptions"
            :disabled="disabled"
            @update:model-value="r.value = ''"
          />
          <UiSelect
            v-if="choicesOf(r.name).length"
            v-model="r.value"
            :options="valueOptions(r.name)"
            :disabled="disabled"
          />
          <UiText
            v-else
            v-model="r.value"
            :placeholder="camera.connected ? 'Value' : 'Connect the camera to pick a value'"
            :disabled="disabled"
          />
          <UiButton
            variant="ghost"
            class="!w-[var(--ctl)] !px-0"
            aria-label="Remove setting"
            :disabled="disabled || s.rows.length <= 1"
            @click="s.rows = s.rows.filter((x) => x.id !== r.id)"
          >
            <UiIcon name="X" />
          </UiButton>
        </div>
        <UiButton
          size="sm"
          variant="ghost"
          class="-ml-2.5 justify-self-start"
          :disabled="disabled || s.rows.length >= MAX_ROWS"
          @click="s.rows.push(newRow())"
        >
          <UiIcon name="Plus" :size="16" />Add setting
        </UiButton>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <UiButton :disabled="disabled || steps.length >= MAX" @click="add">
        <UiIcon name="Plus" :size="16" />Add step
      </UiButton>
      <span class="text-xs text-camera-muted tabular-nums">
        {{ steps.length }} of {{ MIN }} to {{ MAX }} steps
      </span>
    </div>
  </div>
</template>

<style scoped>
/* Label/delay and every setting row share these three tracks so their edges line up. */
.step-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) var(--ctl);
  gap: 12px;
  align-items: end;
}
.step-grid > :last-child {
  align-self: end;
}
@media (max-width: 560px) {
  .step-grid {
    gap: 8px;
  }
}
</style>
