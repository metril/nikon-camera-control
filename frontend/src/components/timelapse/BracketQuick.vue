<script setup>
import { computed } from 'vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useSettingsStore } from '@/stores/settings'
import { useCameraStore } from '@/stores/camera'
import { draft } from './useDraft'
import { bracketTypes, FALLBACK_CHOICES, choicesFor, sortValues, quickShots } from './bracketUtils'

const settings = useSettingsStore()
const camera = useCameraStore()
const quick = computed(() => draft.bracket.quick)

const rows = computed(() =>
  bracketTypes.map((t) => {
    const live = camera.connected ? choicesFor(settings, t.setting) : null
    const values = sortValues([...(live || FALLBACK_CHOICES[t.key]), ...quick.value[t.key]])
    return {
      ...t,
      validated: !!live,
      options: [...new Set(values)].map((v) => ({ value: v, label: v })),
    }
  }),
)

/** The single toggle handler for all four types (UiSegmented multi emits the new list). */
function onToggle(type, next) {
  quick.value[type] = sortValues(next)
}

const modes = [
  {
    value: 'sequence',
    label: 'Sequence',
    hint: 'Every type adds its own shots, one after another.',
  },
  {
    value: 'paired',
    label: 'Paired',
    hint: 'Values are combined by position: first with first, and so on.',
  },
]
const shots = computed(() => quickShots(quick.value))
</script>

<template>
  <div class="space-y-4">
    <fieldset v-for="t in rows" :key="t.key" class="space-y-1" :data-type="t.key">
      <legend class="text-sm font-medium text-slate-200">
        {{ t.label }}
        <UiBadge v-if="!t.validated" tone="neutral" class="ml-2">not validated</UiBadge>
      </legend>
      <UiSegmented
        multiple
        :model-value="quick[t.key]"
        :options="t.options"
        @update:model-value="(v) => onToggle(t.key, v)"
      />
    </fieldset>
    <div class="space-y-1">
      <span class="text-sm font-medium text-slate-200">Combine mode</span>
      <UiSegmented
        v-model="quick.combine"
        :options="modes.map(({ value, label }) => ({ value, label }))"
      />
      <p class="text-xs text-slate-400">
        {{ modes.find((m) => m.value === quick.combine).hint }}
        <strong class="text-slate-200" data-test="quick-shots">{{ shots }}</strong> shots per set.
      </p>
    </div>
  </div>
</template>
