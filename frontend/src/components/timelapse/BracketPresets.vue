<script setup>
import { ref, computed, onMounted } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiText from '@/components/ui/UiText.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { usePresetsStore } from '@/stores/presets'
import { useToastsStore } from '@/stores/toasts'
import { draft, loadPreset, contentBracketing } from './useDraft'

/** `picker` chooses a saved preset; `save` stores the current Quick or Custom steps as one. */
defineProps({
  variant: { type: String, default: 'picker' },
  disabled: Boolean,
})
const presets = usePresetsStore()
const toasts = useToastsStore()
const selected = ref('')
const newName = ref('')
const naming = ref(false)
const busy = ref(false)

const items = computed(() => presets.bracketPresets)
const current = computed(() => items.value.find((p) => p.id === selected.value))
const options = computed(() => [
  { value: '', label: 'Choose a preset…' },
  ...items.value.map((p) => ({ value: p.id, label: p.builtin ? `${p.name} (built-in)` : p.name })),
])
const content = computed(() => (draft.bracket.mode === 'preset' ? null : contentBracketing()))

onMounted(() => presets.fetch().catch((e) => toasts.error(e)))

async function run(fn) {
  busy.value = true
  try {
    await fn()
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = false
  }
}
/** Picking a preset loads it into the editor, where it can be adjusted. */
function pick(id) {
  selected.value = id
  const p = items.value.find((x) => x.id === id)
  if (p) loadPreset(p)
}
const save = () =>
  run(async () => {
    await presets.create({ kind: 'bracket', name: newName.value.trim(), bracketing: content.value })
    newName.value = ''
    naming.value = false
    toasts.success('Preset saved')
  })
const remove = () =>
  run(async () => {
    await presets.remove(selected.value)
    selected.value = ''
  })
</script>

<template>
  <div v-if="variant === 'picker'" class="grid gap-3">
    <div class="grid gap-2">
      <UiSelect
        :model-value="selected"
        label="Preset"
        :options="options"
        :disabled="disabled"
        @update:model-value="pick"
      />
      <p class="text-xs text-camera-muted">
        A chosen preset opens in Quick or Custom steps, where you can adjust it.
      </p>
    </div>
    <div v-if="current && !current.builtin">
      <UiConfirmButton
        size="sm"
        variant="danger"
        :disabled="disabled"
        :loading="busy"
        confirm-text="Delete preset?"
        @confirm="remove"
      >
        <UiIcon name="Trash2" :size="16" />Delete preset
      </UiConfirmButton>
    </div>
  </div>
  <div v-else-if="content" class="flex flex-wrap items-end gap-2">
    <UiButton
      v-if="!naming"
      size="sm"
      variant="ghost"
      class="-ml-2.5"
      :disabled="disabled"
      @click="naming = true"
    >
      <UiIcon name="Bookmark" :size="16" />Save as preset
    </UiButton>
    <template v-else>
      <div class="min-w-[200px] flex-1">
        <UiText v-model="newName" label="Preset name" placeholder="Name" :maxlength="80" />
      </div>
      <UiButton variant="primary" :disabled="!newName.trim()" :loading="busy" @click="save">
        Save preset
      </UiButton>
      <UiButton variant="ghost" @click="naming = false">Cancel</UiButton>
    </template>
  </div>
</template>
