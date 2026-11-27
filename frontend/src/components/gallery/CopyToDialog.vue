<script setup>
import { computed, ref, watch } from 'vue'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import { useStorageStore } from '@/stores/storage'
import { storageName } from '@/labels'

/** Pick another mounted storage to copy the selected files to (the originals stay). */
const props = defineProps({ open: Boolean, count: { type: Number, default: 0 }, busy: Boolean })
const emit = defineEmits(['close', 'confirm'])
const storage = useStorageStore()

const options = computed(() => storage.mounted.filter((l) => l.id !== storage.targetId))
const choice = ref(null)
watch(
  () => [props.open, options.value.map((o) => o.id).join()],
  () => {
    if (!options.value.some((o) => o.id === choice.value))
      choice.value = options.value.length === 1 ? options.value[0].id : null
  },
  { immediate: true },
)
const noun = computed(() => `${props.count} ${props.count === 1 ? 'file' : 'files'}`)
</script>

<template>
  <UiModal :open="open" title="Copy to…" @close="emit('close')">
    <div class="space-y-3" data-testid="copy-dialog">
      <p class="text-sm text-camera-muted">
        Copy {{ noun }} to another storage. The originals stay where they are.
      </p>
      <p v-if="!options.length" class="text-sm" data-testid="copy-none">
        No other storage is mounted. Mount one in Settings first.
      </p>
      <div v-else role="radiogroup" aria-label="Copy to" class="grid gap-2">
        <button
          v-for="o in options"
          :key="o.id"
          type="button"
          role="radio"
          :aria-checked="choice === o.id"
          class="flex min-h-11 items-center rounded-control border px-3 text-left text-sm"
          :class="
            choice === o.id
              ? 'border-camera-accent bg-camera-accent/15'
              : 'border-camera-border bg-camera-raised hover:bg-camera-hover'
          "
          @click="choice = o.id"
        >
          {{ storageName(o) }}
        </button>
      </div>
      <div class="flex justify-end gap-2">
        <UiButton variant="ghost" @click="emit('close')">Cancel</UiButton>
        <UiButton
          variant="primary"
          :disabled="!choice || !count"
          :loading="busy"
          data-testid="copy-confirm"
          @click="emit('confirm', choice)"
        >
          Copy {{ noun }}
        </UiButton>
      </div>
    </div>
  </UiModal>
</template>
