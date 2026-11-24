<script setup>
import { computed } from 'vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useSettingsStore } from '@/stores/settings'
import { useCameraStore } from '@/stores/camera'
import { draft } from './useDraft'
import { bracketTypes, FALLBACK_CHOICES, choicesFor, sortValues, quickShots } from './bracketUtils'

defineProps({ disabled: Boolean })
const settings = useSettingsStore()
const camera = useCameraStore()
const quick = computed(() => draft.bracket.quick)

const rows = computed(() =>
  bracketTypes.map((t) => {
    const live = camera.connected ? choicesFor(settings, t.setting) : null
    const values = sortValues([...(live || FALLBACK_CHOICES[t.key]), ...quick.value[t.key]])
    return { ...t, validated: !!live, values: [...new Set(values)] }
  }),
)

const isOn = (type, v) => quick.value[type].includes(v)
/** The single toggle handler for all four types. */
function toggle(type, v) {
  const cur = quick.value[type]
  quick.value[type] = sortValues(cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v])
}

const modes = [
  {
    value: 'sequence',
    label: 'Sequence',
    hint: 'Each selected value is its own shot.',
  },
  {
    value: 'paired',
    label: 'Paired',
    hint: 'Values are matched by position: the first value of each row goes in shot 1, the second in shot 2, and so on.',
  },
]
const shots = computed(() => quickShots(quick.value))
</script>

<template>
  <div class="grid gap-4">
    <div class="border-t border-camera-subtle">
      <div
        v-for="t in rows"
        :key="t.key"
        class="quick-row border-b border-camera-subtle py-3"
        :data-type="t.key"
      >
        <div class="flex min-h-[var(--ctl-sm)] items-center gap-2 text-[13px] text-camera-muted">
          <span>{{ t.label }}</span>
          <UiBadge v-if="quick[t.key].length">{{ quick[t.key].length }}</UiBadge>
          <UiBadge v-if="!t.validated">Not validated</UiBadge>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="v in t.values"
            :key="v"
            type="button"
            :aria-pressed="isOn(t.key, v)"
            :disabled="disabled"
            class="inline-flex h-[var(--ctl-sm)] min-w-11 items-center justify-center rounded-full border px-2.5 font-mono text-[13px] font-medium tabular-nums disabled:cursor-not-allowed disabled:opacity-[.45]"
            :class="
              isOn(t.key, v)
                ? 'border-camera-text bg-camera-text text-camera-bg'
                : 'border-camera-border bg-camera-bg text-camera-muted hover:border-[#4a4a4a] hover:text-camera-text'
            "
            @click="toggle(t.key, v)"
          >
            {{ v }}
          </button>
        </div>
      </div>
    </div>
    <div class="grid gap-2">
      <span class="text-xs font-medium text-camera-muted">Combine</span>
      <UiSegmented
        v-model="quick.combine"
        class="w-full"
        aria-label="Combine"
        :disabled="disabled"
        :options="modes.map(({ value, label }) => ({ value, label }))"
      />
      <p class="text-xs text-camera-muted">
        {{ modes.find((m) => m.value === quick.combine).hint }}
        <b class="font-medium text-camera-text tabular-nums" data-test="quick-shots">{{ shots }}</b>
        {{ shots === 1 ? 'shot' : 'shots' }} per frame.
      </p>
    </div>
  </div>
</template>

<style scoped>
.quick-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
@media (max-width: 640px) {
  .quick-row {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
