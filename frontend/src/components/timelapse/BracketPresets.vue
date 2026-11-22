<script setup>
import { ref, computed, onMounted } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiText from '@/components/ui/UiText.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiConfirmButton from '@/components/ui/UiConfirmButton.vue'
import { usePresetsStore } from '@/stores/presets'
import { useToastsStore } from '@/stores/toasts'
import { draft, loadPreset, contentBracketing } from './useDraft'

const presets = usePresetsStore()
const toasts = useToastsStore()
const selected = ref('')
const newName = ref('')
const busy = ref(false)

const items = computed(() => presets.bracketPresets)
const current = computed(() => items.value.find((p) => p.id === selected.value))
const options = computed(() => [
  { value: '', label: 'Choose a preset...' },
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
const load = () => current.value && loadPreset(current.value)
const save = () =>
  run(async () => {
    await presets.create({ kind: 'bracket', name: newName.value.trim(), bracketing: content.value })
    newName.value = ''
    toasts.success('Preset saved')
  })
const remove = () =>
  run(async () => {
    await presets.remove(selected.value)
    selected.value = ''
  })
</script>

<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-end gap-2">
      <UiSelect v-model="selected" label="Preset" :options="options" />
      <UiButton :disabled="!current" @click="load">Load</UiButton>
      <UiConfirmButton
        variant="danger"
        :disabled="!current || current.builtin"
        :loading="busy"
        @confirm="remove"
      >
        Delete
      </UiConfirmButton>
    </div>
    <div class="flex flex-wrap items-end gap-2">
      <UiText
        v-model="newName"
        label="Save current as preset"
        placeholder="Preset name"
        :maxlength="80"
      />
      <UiButton :disabled="!content || !newName.trim()" :loading="busy" @click="save"
        >Save preset</UiButton
      >
    </div>
  </div>
</template>
