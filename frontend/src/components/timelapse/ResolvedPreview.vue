<script setup>
import { computed } from 'vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { applied, dirty } from './useDraft'

const result = computed(() => applied.result)
const steps = computed(() => result.value?.resolved_steps ?? [])
</script>

<template>
  <div v-if="result && steps.length" class="space-y-2" aria-live="polite">
    <div class="flex items-center gap-2 text-sm">
      <span class="font-medium">Resolved steps</span>
      <UiBadge :tone="result.validated ? 'ok' : 'warn'">
        {{ result.validated ? 'Validated against camera' : 'Not validated (checked on start)' }}
      </UiBadge>
      <UiBadge v-if="dirty" tone="info">stale</UiBadge>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-left text-sm">
        <thead class="text-xs text-slate-400">
          <tr>
            <th class="pr-3">#</th>
            <th class="pr-3">Label</th>
            <th class="pr-3">Settings</th>
            <th>Delay</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in steps" :key="s.index" class="border-t border-slate-700">
            <td class="pr-3">{{ s.index + 1 }}</td>
            <td class="pr-3">{{ s.label }}</td>
            <td class="pr-3">
              {{
                Object.entries(s.settings)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(', ')
              }}
            </td>
            <td>{{ s.delay_ms }} ms</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
