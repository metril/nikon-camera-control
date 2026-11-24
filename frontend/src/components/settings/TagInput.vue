<script setup>
import { ref } from 'vue'
import { uid } from '@/components/ui/uid'
import UiIcon from '@/components/ui/UiIcon.vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  label: { type: String, default: '' },
  placeholder: { type: String, default: 'Add and press Enter' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const id = uid('tags')
const draft = ref('')

function add() {
  const v = draft.value.trim().replace(/,$/, '')
  draft.value = ''
  if (v && !props.modelValue.includes(v)) emit('update:modelValue', [...props.modelValue, v])
}
function onKey(e) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    add()
  }
}
const remove = (v) =>
  emit(
    'update:modelValue',
    props.modelValue.filter((x) => x !== v),
  )
</script>

<template>
  <div class="flex flex-col gap-1">
    <label v-if="label" :for="id" class="text-xs font-medium text-camera-muted">{{ label }}</label>
    <div
      class="flex min-h-[var(--ctl)] flex-wrap items-center gap-1 rounded-control border border-camera-border bg-camera-bg p-1.5"
    >
      <span
        v-for="v in modelValue"
        :key="v"
        class="inline-flex items-center gap-1 rounded bg-camera-raised px-2 py-0.5 text-xs"
      >
        {{ v }}
        <button
          type="button"
          :aria-label="`Remove ${v}`"
          :disabled="disabled"
          class="inline-flex text-camera-muted hover:text-camera-text"
          @click="remove(v)"
        >
          <UiIcon name="X" :size="12" />
        </button>
      </span>
      <input
        :id="id"
        v-model="draft"
        :placeholder="placeholder"
        :disabled="disabled"
        class="min-w-[8rem] flex-1 bg-transparent px-1 py-0.5 text-sm outline-offset-4"
        @keydown="onKey"
        @blur="add"
      />
    </div>
  </div>
</template>
