<script setup>
import { computed } from 'vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { settingName } from '@/labels'
import { resultNow, fresh } from './useDraft'

const result = resultNow
const steps = computed(() => result.value?.resolved_steps ?? [])
const describe = (s) =>
  Object.entries(s.settings)
    .map(([k, v]) => `${settingName(k)} ${v}`)
    .join(', ')
const delay = (ms) => (ms ? ` · after ${ms / 1000} s` : '')
</script>

<template>
  <div v-if="result && steps.length" class="grid gap-2" aria-live="polite">
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs font-medium text-camera-muted">Each frame takes these shots</span>
      <UiBadge :tone="result.validated ? 'ok' : 'warn'">
        {{ result.validated ? 'Validated against camera' : 'Checked on start' }}
      </UiBadge>
      <UiBadge v-if="!fresh">Out of date</UiBadge>
    </div>
    <div class="flex flex-wrap gap-1.5" data-test="resolved-steps">
      <UiBadge
        v-for="s in steps"
        :key="s.index"
        class="!h-auto min-h-[22px] !whitespace-normal py-0.5"
      >
        <span class="tabular-nums">{{ s.index + 1 }}</span><template v-if="s.label">
          {{ s.label }}</template
        >
        · {{ describe(s) }}{{ delay(s.delay_ms) }}
      </UiBadge>
    </div>
  </div>
</template>
