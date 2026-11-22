<script setup>
import { ref, watch, nextTick } from 'vue'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const jobs = useJobsStore()
const toasts = useToastsStore()
const closeBtn = ref(null)
const cancelling = ref({})

const ACTIVE = ['queued', 'pending', 'running']
const isActive = (j) => ACTIVE.includes(j.status)
const TONES = {
  queued: 'neutral',
  running: 'info',
  completed: 'ok',
  failed: 'error',
  cancelled: 'warn',
}

/** Toast when a job we saw running finishes. Jobs first seen already finished never toast. */
const seen = new Map()
watch(
  () => jobs.byId,
  (byId) => {
    for (const j of Object.values(byId)) {
      const before = seen.get(j.id)
      seen.set(j.id, j.status)
      if (before === undefined || !ACTIVE.includes(before)) continue
      if (j.status === 'completed') toasts.success(`Job finished: ${j.kind}`)
      else if (j.status === 'failed')
        toasts.error(`Job failed: ${j.kind}${j.error ? ` - ${j.error}` : ''}`)
    }
  },
  { immediate: true, deep: true },
)

watch(
  () => props.open,
  async (o) => {
    if (o) {
      await nextTick()
      closeBtn.value?.focus()
    }
  },
)

async function cancel(id) {
  cancelling.value = { ...cancelling.value, [id]: true }
  try {
    await jobs.cancel(id)
  } catch (e) {
    toasts.error(e)
  } finally {
    cancelling.value = { ...cancelling.value, [id]: false }
  }
}
function summary(j) {
  if (j.error) return j.error
  const r = j.result
  if (!r || typeof r !== 'object') return ''
  return Object.entries(r)
    .filter(([, v]) => v == null || typeof v !== 'object')
    .slice(0, 4)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ')
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-40 flex justify-end bg-black/50"
      @mousedown.self="emit('close')"
    >
      <aside
        role="dialog"
        aria-label="Jobs"
        class="flex h-full w-full max-w-md flex-col border-l border-camera-border bg-camera-surface shadow-xl"
        @keydown.esc="emit('close')"
      >
        <header class="flex items-center justify-between border-b border-camera-border px-4 py-3">
          <h2 class="text-base font-semibold">Jobs</h2>
          <button
            ref="closeBtn"
            type="button"
            aria-label="Close jobs panel"
            class="rounded px-2 text-xl leading-none text-camera-muted hover:text-camera-text"
            @click="emit('close')"
          >
            &times;
          </button>
        </header>
        <ul class="flex-1 divide-y divide-camera-border overflow-y-auto" aria-live="polite">
          <li
            v-for="j in jobs.list"
            :key="j.id"
            class="flex flex-col gap-2 px-4 py-3"
            data-test="job"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium">{{ j.kind }}</span>
              <UiBadge :tone="TONES[j.status] || 'neutral'">{{ j.status }}</UiBadge>
            </div>
            <UiProgress v-if="isActive(j)" :value="j.progress ?? null" :label="j.message || ''" />
            <p v-else-if="j.message" class="text-sm text-camera-muted">{{ j.message }}</p>
            <p
              v-if="summary(j)"
              class="break-words text-xs"
              :class="j.error ? 'text-red-400' : 'text-camera-muted'"
            >
              {{ summary(j) }}
            </p>
            <div v-if="isActive(j)">
              <UiConfirmButton
                size="sm"
                variant="ghost"
                confirm-text="Cancel job?"
                :loading="!!cancelling[j.id]"
                @confirm="cancel(j.id)"
              >
                Cancel
              </UiConfirmButton>
            </div>
          </li>
        </ul>
        <UiEmpty
          v-if="!jobs.list.length"
          title="No jobs"
          hint="Background work such as video rendering shows up here."
        />
      </aside>
    </div>
  </Teleport>
</template>
