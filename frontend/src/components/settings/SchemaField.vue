<script setup>
import { computed } from 'vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiText from '@/components/ui/UiText.vue'
import { configEnum } from '@/labels'
import SettingRow from './SettingRow.vue'
import TagInput from './TagInput.vue'

const props = defineProps({
  field: { type: Object, required: true },
  modelValue: { type: null, default: null },
  dirty: Boolean,
  error: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const text = computed(() => (props.modelValue == null ? '' : String(props.modelValue)))
const onText = (v) => emit('update:modelValue', v === '' && props.field.nullable ? null : v)
const options = computed(() =>
  (props.field.options || []).map((v) => ({ value: v, label: configEnum(props.field.name, v) })),
)
</script>

<template>
  <SettingRow
    :title="field.title"
    :description="field.description"
    :dirty="dirty"
    :error="error"
    :natural="field.kind === 'boolean'"
    :data-field="field.name"
  >
    <UiToggle
      v-if="field.kind === 'boolean'"
      :model-value="!!modelValue"
      :aria-label="field.title"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <UiSelect
      v-else-if="field.kind === 'enum'"
      :model-value="modelValue"
      :options="options"
      :label="field.title"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <UiNumber
      v-else-if="field.kind === 'number' || field.kind === 'integer'"
      :model-value="modelValue"
      :label="field.title"
      :min="field.min"
      :max="field.max"
      :step="field.step"
      :unit="field.unit"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <TagInput
      v-else-if="field.kind === 'strings'"
      :model-value="modelValue || []"
      :label="field.title"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <UiText v-else :model-value="text" :label="field.title" @update:model-value="onText" />
  </SettingRow>
</template>
