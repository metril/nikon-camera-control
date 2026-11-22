<script setup>
import { computed } from 'vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiText from '@/components/ui/UiText.vue'
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
const label = computed(() => props.field.title + (props.dirty ? ' *' : ''))
</script>

<template>
  <div class="flex flex-col gap-1" :data-field="field.name" :data-dirty="dirty || undefined">
    <UiToggle
      v-if="field.kind === 'boolean'"
      :model-value="!!modelValue"
      :label="label"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <UiSelect
      v-else-if="field.kind === 'enum'"
      :model-value="modelValue"
      :options="field.options"
      :label="label"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <UiNumber
      v-else-if="field.kind === 'number' || field.kind === 'integer'"
      :model-value="modelValue"
      :label="label"
      :min="field.min"
      :max="field.max"
      :step="field.step"
      :unit="field.unit"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <TagInput
      v-else-if="field.kind === 'strings'"
      :model-value="modelValue || []"
      :label="label"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <UiText v-else :model-value="text" :label="label" @update:model-value="onText" />
    <p v-if="field.description" class="text-xs text-camera-muted">{{ field.description }}</p>
    <p v-if="error" class="text-xs text-red-400" role="alert" data-test="field-error">
      {{ error }}
    </p>
  </div>
</template>
