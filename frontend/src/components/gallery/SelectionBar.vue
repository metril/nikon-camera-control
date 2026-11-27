<script setup>
import { ref, watch } from 'vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { useLayoutMode } from '@/composables/useLayoutMode'

/**
 * The selection toolbar. Touch: Select all, Copy to…, Delete, Done (no download).
 * Desktop: Select all, Download as ZIP, Copy to…, Delete and a clear button.
 * Delete asks inline first ("Delete N items" / "Keep").
 */
const props = defineProps({
  count: { type: Number, default: 0 },
  allSelected: Boolean,
  /** Desktop only: offers "Download as ZIP". */
  zip: { type: Boolean, default: true },
  copyLabel: { type: String, default: 'Copy to…' },
  copyDisabled: Boolean,
  copyTitle: { type: String, default: '' },
  deleteDisabled: Boolean,
  deleteTitle: { type: String, default: '' },
  busy: Boolean,
})
const emit = defineEmits(['toggle-all', 'zip', 'copy', 'delete', 'done'])
const { isTouch } = useLayoutMode()
const confirming = ref(false)
watch(
  () => props.count,
  () => (confirming.value = false),
)
function confirmDelete() {
  confirming.value = false
  emit('delete')
}
</script>

<template>
  <div
    role="toolbar"
    aria-label="Selection"
    data-testid="select-bar"
    class="flex shrink-0 flex-wrap items-center gap-2 rounded-card border border-[#5a3a1e] bg-[#2a1a0d] px-3"
    :class="isTouch ? 'min-h-16 py-2 pl-4 pr-2' : 'min-h-11 py-1'"
  >
    <span
      class="font-semibold tabular-nums"
      :class="isTouch ? 'text-[17px]' : ''"
      aria-live="polite"
      >{{ count }} selected</span
    >
    <span class="hidden text-[13px] text-camera-muted min-[900px]:inline">
      <template v-if="isTouch">Tap photos to add or remove</template>
      <template v-else>
        Shift-click to select a range · <kbd>Ctrl</kbd>+<kbd>A</kbd> selects all
      </template>
    </span>
    <div class="ml-auto flex flex-wrap items-center gap-2">
      <UiButton :size="isTouch ? 'md' : 'sm'" @click="emit('toggle-all')">{{
        allSelected ? 'Clear' : 'Select all'
      }}</UiButton>
      <UiButton
        v-if="zip && !isTouch"
        size="sm"
        :disabled="!count || busy"
        data-testid="zip"
        @click="emit('zip')"
      >
        Download as ZIP
      </UiButton>
      <UiButton
        :size="isTouch ? 'md' : 'sm'"
        :disabled="!count || copyDisabled || busy"
        :title="copyTitle"
        data-testid="copy-to"
        @click="emit('copy')"
      >
        {{ copyLabel }}
      </UiButton>
      <template v-if="confirming">
        <UiButton
          :size="isTouch ? 'md' : 'sm'"
          variant="danger"
          :loading="busy"
          @click="confirmDelete"
        >
          Delete {{ count }} {{ count === 1 ? 'item' : 'items' }}
        </UiButton>
        <UiButton :size="isTouch ? 'md' : 'sm'" variant="ghost" @click="confirming = false"
          >Keep</UiButton
        >
      </template>
      <UiButton
        v-else
        :size="isTouch ? 'md' : 'sm'"
        class="!text-camera-danger"
        :disabled="!count || deleteDisabled || busy"
        :title="deleteTitle"
        data-testid="delete"
        @click="confirming = true"
      >
        <UiIcon name="Trash2" :size="16" />Delete
      </UiButton>
      <UiButton
        v-if="isTouch"
        variant="primary"
        data-testid="done"
        :disabled="busy"
        @click="emit('done')"
      >
        Done
      </UiButton>
      <button
        v-else
        type="button"
        aria-label="Clear selection"
        class="inline-flex h-8 w-8 items-center justify-center rounded-control text-camera-muted hover:text-camera-text"
        data-testid="done"
        @click="emit('done')"
      >
        <UiIcon name="X" :size="16" />
      </button>
    </div>
  </div>
</template>
