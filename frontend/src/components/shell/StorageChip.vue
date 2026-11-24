<script setup>
import { computed, ref } from 'vue'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import UiBadge from '@/components/ui/UiBadge.vue'
import { formatBytes } from './format'

const storage = useStorageStore()
const toasts = useToastsStore()
const open = ref(false)

const candidates = computed(() => storage.mounted.filter((l) => l.id !== storage.targetId))
const backupText = computed(() => {
  const b = storage.backup
  if (!b) return ''
  if (b.running) return `Backing up${b.pending ? ` (${b.pending} left)` : ''}`
  return b.pending ? `${b.pending} to back up` : ''
})
async function pick(id) {
  open.value = false
  try {
    await storage.setTarget(id)
  } catch (e) {
    toasts.error(e)
  }
}
</script>

<template>
  <span v-if="storage.loaded" class="relative flex items-center gap-1" data-test="storage-chip">
    <button
      type="button"
      class="inline-flex items-center gap-1 rounded-full focus-visible:outline-offset-2"
      :aria-expanded="open"
      aria-label="Storage target"
      @click="open = !open"
    >
      <UiBadge v-if="!storage.target" tone="warn" data-test="chip-none">No storage target</UiBadge>
      <UiBadge v-else :tone="storage.target.mounted ? 'ok' : 'error'" data-test="chip-target">
        {{ storage.target.name || storage.target.label || storage.target.id }}
        <template v-if="storage.target.mounted">
          · {{ formatBytes(storage.target.free) }} free</template
        >
        <template v-else> · offline</template>
      </UiBadge>
    </button>
    <UiBadge
      v-if="backupText"
      :tone="storage.backup?.running ? 'info' : 'warn'"
      data-test="chip-backup"
    >
      {{ backupText }}
    </UiBadge>
    <ul
      v-if="open"
      class="absolute left-0 top-full z-20 mt-1 min-w-48 rounded-md border border-camera-border bg-camera-surface p-1 text-sm shadow-lg"
      data-test="chip-menu"
    >
      <li v-for="l in candidates" :key="l.id">
        <button
          type="button"
          class="w-full rounded px-2 py-1 text-left hover:bg-camera-border"
          :data-test="`switch-${l.id}`"
          @click="pick(l.id)"
        >
          {{ l.name || l.label || l.id }}
        </button>
      </li>
      <li v-if="!candidates.length" class="px-2 py-1 text-camera-muted">No other mounted drive</li>
    </ul>
  </span>
</template>
