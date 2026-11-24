<script setup>
import { ref, watch } from 'vue'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { jobKind, jobStatus } from '@/labels'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiProgress from '@/components/ui/UiProgress.vue'
import { jobSummary } from './jobSummary'

defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const jobs = useJobsStore()
const toasts = useToastsStore()
const cancelling = ref({})

const ACTIVE = ['queued', 'pending', 'running']
const isActive = (j) => ACTIVE.includes(j.status)
const TONES = {
  queued: 'neutral',
  pending: 'neutral',
  running: 'accent',
  completed: 'ok',
  failed: 'danger',
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
      if (j.status === 'completed') toasts.success(`${jobKind(j.kind)} finished`)
      else if (j.status === 'failed')
        toasts.error(`${jobKind(j.kind)} failed${j.error ? `: ${j.error}` : ''}`)
    }
  },
  { immediate: true, deep: true },
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
</script>

<template>
  <UiModal :open="open" variant="side" title="Jobs" @close="emit('close')">
    <ul v-if="jobs.list.length" class="flex flex-col" aria-live="polite">
      <li
        v-for="j in jobs.list"
        :key="j.id"
        class="flex flex-col gap-2 border-b border-camera-subtle py-3 first:pt-0 last:border-b-0"
        data-test="job"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="min-w-0 truncate font-medium">{{ jobKind(j.kind) }}</span>
          <UiBadge :tone="TONES[j.status] || 'neutral'">{{ jobStatus(j.status) }}</UiBadge>
        </div>
        <UiProgress v-if="isActive(j)" :value="j.progress ?? null" :label="j.message || ''" />
        <p v-else-if="j.message" class="text-sm text-camera-muted">{{ j.message }}</p>
        <p
          v-if="jobSummary(j)"
          class="break-words text-[12.5px]"
          :class="j.error ? 'text-camera-danger' : 'text-camera-muted'"
          data-test="summary"
        >
          {{ jobSummary(j) }}
        </p>
        <div v-if="isActive(j)">
          <UiConfirmButton
            size="sm"
            variant="ghost"
            class="-ml-2.5"
            confirm-text="Cancel job?"
            :loading="!!cancelling[j.id]"
            @confirm="cancel(j.id)"
          >
            Cancel
          </UiConfirmButton>
        </div>
      </li>
    </ul>
    <div v-else class="flex flex-col items-center gap-2.5 px-4 py-8 text-center text-camera-muted">
      <UiIcon name="ListChecks" :size="28" />
      <b class="text-[15px] text-camera-text">No jobs</b>
      <span>Video renders and file transfers show here.</span>
    </div>
  </UiModal>
</template>
