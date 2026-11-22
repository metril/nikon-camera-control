<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useFocusStore } from '@/stores/focus'
import { useToastsStore } from '@/stores/toasts'
import AdvCard from './AdvCard.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiBadge from '@/components/ui/UiBadge.vue'
import { useHoldRepeat } from './useHoldRepeat'
import { finite, readJson, writeJson } from './helpers'

const KEY = 'advanced.focusSteps'
const focus = useFocusStore()
const toasts = useToastsStore()

const sizes = reactive(readJson(KEY, { fine: 5, medium: 50, coarse: 500 }))
const size = ref('medium')
const sizeOptions = [
  { value: 'fine', label: 'Fine' },
  { value: 'medium', label: 'Medium' },
  { value: 'coarse', label: 'Coarse' },
]
watch(sizes, (v) => writeJson(KEY, v), { deep: true })

const afBusy = ref(false)
const afResult = ref(null)
const resetBusy = ref(false)

const amount = () => {
  const n = sizes[size.value]
  return finite(n) && n >= 1 ? Math.round(n) : 1
}
// Negative steps move focus nearer, positive farther.
const buttons = [
  { label: '◀◀', aria: 'Near, large step', dir: -1, mult: 4 },
  { label: '◀', aria: 'Near', dir: -1, mult: 1 },
  { label: '▶', aria: 'Far', dir: 1, mult: 1 },
  { label: '▶▶', aria: 'Far, large step', dir: 1, mult: 4 },
]
let pending = 0
const hold = useHoldRepeat(() => focus.manual(pending), { onError: (e) => toasts.error(e) })
function press(b) {
  pending = b.dir * b.mult * amount()
  hold.start()
}
function key(b) {
  pending = b.dir * b.mult * amount()
  hold.once()
}

async function autofocus() {
  afBusy.value = true
  afResult.value = null
  try {
    const r = await focus.autofocus()
    afResult.value = r?.focused === false ? 'failed' : r?.focused ? 'focused' : 'unknown'
  } catch (e) {
    afResult.value = 'failed'
    toasts.error(e)
  } finally {
    afBusy.value = false
  }
}
async function zero() {
  resetBusy.value = true
  try {
    await focus.reset()
  } catch (e) {
    toasts.error(e)
  } finally {
    resetBusy.value = false
  }
}

onMounted(() => focus.fetchStatus().catch(() => {}))
</script>

<template>
  <AdvCard title="Focus" subtitle="Autofocus and manual drive">
    <template #default="{ disabled, reason }">
      <div class="flex flex-wrap items-center gap-3">
        <UiButton
          variant="primary"
          :loading="afBusy"
          :disabled="disabled"
          :title="reason"
          @click="autofocus"
        >
          Autofocus
        </UiButton>
        <span aria-live="polite" data-testid="af-result">
          <UiBadge v-if="afResult === 'focused'" tone="ok">Focused</UiBadge>
          <UiBadge v-else-if="afResult === 'failed'" tone="error">Focus failed</UiBadge>
          <UiBadge v-else-if="afResult === 'unknown'" tone="neutral">Done</UiBadge>
        </span>
      </div>

      <div class="space-y-2">
        <p class="text-xs text-slate-400">
          Manual focus (hold to repeat). Live view is enabled automatically for the move.
        </p>
        <UiSegmented v-model="size" :options="sizeOptions" :disabled="disabled" />
        <div class="flex items-center gap-2">
          <button
            v-for="b in buttons"
            :key="b.aria"
            type="button"
            :aria-label="b.aria"
            :disabled="disabled"
            class="min-w-12 select-none touch-none rounded bg-slate-700 px-3 py-2 text-lg hover:bg-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400 disabled:opacity-50"
            @pointerdown.prevent="press(b)"
            @pointerup="hold.stop()"
            @pointerleave="hold.stop()"
            @pointercancel="hold.stop()"
            @click="$event.detail === 0 && key(b)"
          >
            {{ b.label }}
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-3 text-sm">
          <span>
            Position:
            <strong data-testid="focus-pos">{{ focus.status?.relative_position ?? '–' }}</strong>
            <span v-if="focus.status?.range" class="text-slate-400">
              (range {{ focus.status.range.min }} to {{ focus.status.range.max }} per move)
            </span>
          </span>
          <UiButton size="sm" :loading="resetBusy" :disabled="disabled" @click="zero"
            >Set zero</UiButton
          >
        </div>
      </div>

      <details class="text-sm">
        <summary class="cursor-pointer text-slate-300">Step sizes</summary>
        <div class="mt-2 grid grid-cols-3 gap-2">
          <UiNumber v-model="sizes.fine" label="Fine" :min="1" :step="1" />
          <UiNumber v-model="sizes.medium" label="Medium" :min="1" :step="1" />
          <UiNumber v-model="sizes.coarse" label="Coarse" :min="1" :step="1" />
        </div>
      </details>
    </template>
  </AdvCard>
</template>
