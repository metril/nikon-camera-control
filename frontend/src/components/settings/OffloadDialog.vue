<script setup>
import { ref, computed, watch } from 'vue'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import { useSessionsStore } from '@/stores/sessions'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiToggle from '@/components/ui/UiToggle.vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])
const storage = useStorageStore()
const toasts = useToastsStore()
const sessions = useSessionsStore()

const SCOPES = [
  { value: 'all', label: 'Everything' },
  { value: 'session', label: 'One session' },
  { value: 'older_than', label: 'Older than' },
]
const from = ref('')
const to = ref('')
const kind = ref('all')
const sessionId = ref('')
const sessionsLoading = ref(false)
const before = ref('')
const keepSource = ref(true)
const busy = ref(false)

const options = computed(() =>
  storage.mounted.map((l) => ({ value: l.id, label: l.name || l.label || l.id })),
)
const toOptions = computed(() => options.value.filter((o) => o.value !== from.value))
const fmtDate = (iso) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { dateStyle: 'medium' })
}
const sessionOptions = computed(() =>
  sessions.items.map((s) => ({
    value: s.id,
    label: [s.name || 'Untitled session', fmtDate(s.created)].filter(Boolean).join(' · '),
  })),
)
const valid = computed(
  () =>
    from.value &&
    to.value &&
    from.value !== to.value &&
    (kind.value !== 'session' || sessionId.value) &&
    (kind.value !== 'older_than' || before.value),
)

watch(
  () => props.open,
  (o) => {
    if (!o) return
    from.value = storage.targetId || options.value[0]?.value || ''
    to.value = options.value.find((x) => x.value !== from.value)?.value || ''
  },
)
watch(kind, async (k) => {
  if (k !== 'session' || sessions.items.length) return
  sessionsLoading.value = true
  try {
    await sessions.fetch({ limit: 200 })
  } catch (e) {
    toasts.error(e)
  } finally {
    sessionsLoading.value = false
  }
})
watch(sessionOptions, (o) => {
  if (!o.some((x) => x.value === sessionId.value)) sessionId.value = o[0]?.value || ''
})

async function submit() {
  busy.value = true
  try {
    const scope = { kind: kind.value }
    if (kind.value === 'session') scope.session_id = sessionId.value
    if (kind.value === 'older_than') scope.before = new Date(before.value).toISOString()
    await storage.offload({
      from_id: from.value,
      to_id: to.value,
      scope,
      keep_source: keepSource.value,
    })
    toasts.success('Offload started. Progress is in Jobs.')
    emit('close')
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <UiModal :open="open" title="Offload files" @close="emit('close')">
    <div class="flex flex-col gap-3" data-test="offload-dialog">
      <UiSelect v-model="from" :options="options" label="From" />
      <UiSelect v-model="to" :options="toOptions" label="To" />
      <UiSegmented v-model="kind" :options="SCOPES" aria-label="Scope" />
      <template v-if="kind === 'session'">
        <UiSelect
          v-if="sessionOptions.length"
          v-model="sessionId"
          :options="sessionOptions"
          label="Session"
          data-test="session-picker"
        />
        <p v-else class="text-sm text-camera-muted" data-test="no-sessions">
          {{ sessionsLoading ? 'Loading sessions…' : 'No sessions yet.' }}
        </p>
      </template>
      <label
        v-if="kind === 'older_than'"
        class="flex flex-col gap-1.5 text-xs font-medium text-camera-muted"
      >
        Older than
        <input
          v-model="before"
          type="datetime-local"
          class="h-[var(--ctl)] w-full min-w-0 rounded-control border border-camera-border bg-camera-bg px-3 text-sm text-camera-text"
          data-test="before"
        />
      </label>
      <UiToggle v-model="keepSource" label="Keep source files (copy only)" />
      <p v-if="!keepSource" class="text-xs text-camera-warn">
        Source files are deleted only after the copy is verified.
      </p>
    </div>
    <template #footer>
      <UiButton @click="emit('close')">Cancel</UiButton>
      <UiButton
        variant="primary"
        :disabled="!valid"
        :loading="busy"
        data-test="offload-go"
        @click="submit"
      >
        Start offload
      </UiButton>
    </template>
  </UiModal>
</template>
