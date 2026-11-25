<script setup>
import { ref, computed, watch } from 'vue'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import UiModal from '@/components/ui/UiModal.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiText from '@/components/ui/UiText.vue'
import { formatBytes } from '@/components/shell/format'
import { FORMAT_FS, FAT32_BIG_NOTE, fsDisabled, labelError } from './formatDrive'

const props = defineProps({
  open: Boolean,
  /** { name, majmin, size, model, items: LocationOut[] } */
  disk: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const storage = useStorageStore()
const toasts = useToastsStore()

const fstype = ref('exfat')
const label = ref('')
const typed = ref('')
const busy = ref(false)

watch(
  () => props.open,
  (o) => {
    if (!o) return
    fstype.value = 'exfat'
    label.value = ''
    typed.value = ''
  },
)

const fs = computed(() => FORMAT_FS.find((f) => f.value === fstype.value))
const err = computed(() => labelError(fstype.value, label.value))
const ready = computed(
  () =>
    !!props.disk &&
    typed.value === props.disk.name &&
    !err.value &&
    !fsDisabled(fstype.value, props.disk.size),
)
const partName = (l) => l.label || l.name || l.id

async function submit() {
  if (!ready.value) return
  busy.value = true
  try {
    await storage.formatDisk(props.disk.name, {
      fstype: fstype.value,
      label: label.value,
      majmin: props.disk.majmin,
      size: props.disk.size,
      diskseq: props.disk.diskseq,
    })
    toasts.success('Formatting started. Progress is in Jobs.')
    emit('close')
  } catch (e) {
    toasts.error(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <UiModal :open="open" title="Format drive" @close="emit('close')">
    <div v-if="disk" class="flex flex-col gap-3" data-test="format-dialog">
      <p class="text-sm text-camera-danger" data-test="format-warning">
        Everything on this drive will be erased and cannot be recovered.
      </p>
      <p class="break-words text-sm" data-test="format-disk">
        <span class="font-medium">{{ disk.model || 'USB drive' }}</span> ·
        {{ formatBytes(disk.size) }} ·
        <span class="font-mono">{{ disk.name }}</span>
      </p>
      <ul class="flex flex-col gap-1 text-sm" data-test="format-parts">
        <li
          v-for="l in disk.items"
          :key="l.id"
          class="rounded-inner border border-camera-border px-3 py-1.5"
        >
          <span class="break-all">{{ partName(l) }}</span>
          <span class="text-xs text-camera-muted">
            · {{ l.fstype || 'unknown filesystem' }}
            <template v-if="l.size != null"> · {{ formatBytes(l.size) }}</template>
          </span>
        </li>
      </ul>
      <UiSelect
        v-model="fstype"
        :options="
          FORMAT_FS.map((f) => ({
            value: f.value,
            label: f.label,
            disabled: fsDisabled(f.value, disk.size),
          }))
        "
        label="Filesystem"
        data-test="format-fs"
      />
      <p class="text-xs text-camera-muted" data-test="format-fs-note">
        {{ fsDisabled('fat32', disk.size) ? FAT32_BIG_NOTE + '. ' : '' }}{{ fs.note }}
      </p>
      <UiText
        v-model="label"
        label="Label (optional)"
        :maxlength="fs.max"
        data-test="format-label"
      />
      <p v-if="err" class="text-xs text-camera-danger" data-test="format-label-error">{{ err }}</p>
      <UiText
        v-model="typed"
        :label="`Type ${disk.name} to confirm`"
        :placeholder="disk.name"
        data-test="format-confirm"
      />
    </div>
    <template #footer>
      <UiButton @click="emit('close')">Cancel</UiButton>
      <UiButton
        variant="danger"
        :disabled="!ready"
        :loading="busy"
        data-test="format-go"
        @click="submit"
      >
        Format drive
      </UiButton>
    </template>
  </UiModal>
</template>
