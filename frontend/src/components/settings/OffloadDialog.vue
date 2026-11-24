<script setup>
import { ref, computed, watch } from 'vue'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiText from '@/components/ui/UiText.vue'
import UiToggle from '@/components/ui/UiToggle.vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])
const storage = useStorageStore()
const toasts = useToastsStore()

const SCOPES = [
  { value: 'all', label: 'Everything' },
  { value: 'session', label: 'One session' },
  { value: 'older_than', label: 'Older than' },
]
const from = ref('')
const to = ref('')
const kind = ref('all')
const sessionId = ref('')
const before = ref('')
const keepSource = ref(true)
const busy = ref(false)

const options = computed(() =>
  storage.mounted.map((l) => ({ value: l.id, label: l.name || l.label || l.id })),
)
const toOptions = computed(() => options.value.filter((o) => o.value !== from.value))
const valid = computed(
  () =>
    from.value &&
    to.value &&
    from.value !== to.value &&
    (kind.value !== 'session' || sessionId.value.trim()) &&
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

async function submit() {
  busy.value = true
  try {
    const scope = { kind: kind.value }
    if (kind.value === 'session') scope.session_id = sessionId.value.trim()
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
      <UiText v-if="kind === 'session'" v-model="sessionId" label="Session id" />
      <label v-if="kind === 'older_than'" class="flex flex-col gap-1 text-sm">
        Older than
        <input
          v-model="before"
          type="datetime-local"
          class="rounded border border-camera-border bg-camera-bg px-2 py-1.5"
          data-test="before"
        />
      </label>
      <UiToggle v-model="keepSource" label="Keep source files (copy only)" />
      <p v-if="!keepSource" class="text-xs text-camera-warning">
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
