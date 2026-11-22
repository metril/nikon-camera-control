<script setup>
import { computed } from 'vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiSegmented from '@/components/ui/UiSegmented.vue'
import UiNumber from '@/components/ui/UiNumber.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

const props = defineProps({
  setting: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
  reason: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['change'])

const s = computed(() => props.setting)
const editable = computed(() => s.value.writable && !s.value.readonly)
const kind = computed(() => {
  if (!editable.value) return 'readonly'
  const t = s.value.type
  if (t === 'radio' || t === 'menu') return s.value.choices?.length ? 'choice' : 'readonly'
  if (t === 'range') return s.value.range ? 'range' : 'readonly'
  if (t === 'toggle') return 'toggle'
  return 'readonly'
})
const short = computed(() => (s.value.choices?.length || 0) <= 4)
const options = computed(() => (s.value.choices || []).map((c) => ({ value: c, label: c })))
const off = computed(() => props.disabled)
const why = computed(() => {
  if (props.reason) return props.reason
  if (!editable.value)
    return s.value.readonly ? 'Read-only on the camera' : 'Not writable through the API'
  return ''
})
// Select/number/toggle render their own associated <label>; the others need a heading.
const segmented = computed(() => kind.value === 'choice' && short.value && s.value.type === 'radio')
const showHeading = computed(() => kind.value === 'readonly' || segmented.value)
const emitChange = (v) => emit('change', s.value.name, v)
</script>

<template>
  <div class="flex flex-col gap-1" :title="why" :data-setting="s.name">
    <div v-if="showHeading || saving" class="flex items-center gap-2">
      <span
        v-if="showHeading"
        :id="`lbl-${s.name}`"
        class="text-xs font-medium text-camera-muted"
        >{{ s.label }}</span
      >
      <UiSpinner v-if="saving" size="sm" data-testid="saving" aria-label="Saving" />
    </div>
    <template v-if="kind === 'choice'">
      <UiSegmented
        v-if="short && s.type === 'radio'"
        :model-value="s.value"
        :options="options"
        :disabled="off"
        :aria-labelledby="`lbl-${s.name}`"
        @update:model-value="emitChange"
      />
      <UiSelect
        v-else
        :model-value="s.value"
        :options="options"
        :label="s.label"
        :disabled="off"
        @update:model-value="emitChange"
      />
    </template>
    <UiNumber
      v-else-if="kind === 'range'"
      :model-value="Number(s.value)"
      :label="s.label"
      :min="s.range.min"
      :max="s.range.max"
      :step="s.range.step"
      :disabled="off"
      snap
      @commit="(v) => v !== null && v !== Number(s.value) && emitChange(v)"
    />
    <UiToggle
      v-else-if="kind === 'toggle'"
      :model-value="!!s.value"
      :label="s.label"
      :disabled="off"
      @update:model-value="emitChange"
    />
    <span v-else class="text-sm text-camera-text" data-testid="readonly-value">{{
      s.value === null || s.value === undefined || s.value === '' ? '--' : String(s.value)
    }}</span>
    <p v-if="error" class="text-xs text-camera-error" role="alert">{{ error }}</p>
  </div>
</template>
