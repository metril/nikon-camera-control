<script setup>
/** Where photos are saved, with a menu to switch to another mounted drive. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import UiBadge from '@/components/ui/UiBadge.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import { formatBytes } from './format'

const storage = useStorageStore()
const toasts = useToastsStore()
const open = ref(false)
const root = ref(null)

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

function outside(e) {
  if (!root.value?.contains(e.target)) open.value = false
}
function onKeydown(e) {
  if (e.key === 'Escape' && open.value) {
    e.stopPropagation()
    open.value = false
    root.value?.querySelector('button')?.focus()
  } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && open.value) {
    e.preventDefault()
    const items = [...root.value.querySelectorAll('[role="menuitem"]')]
    const at = items.indexOf(document.activeElement)
    items[(at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
  }
}
watch(open, (on) => {
  if (on) document.addEventListener('pointerdown', outside, true)
  else document.removeEventListener('pointerdown', outside, true)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside, true))
</script>

<template>
  <span
    v-if="storage.loaded"
    ref="root"
    class="relative flex flex-wrap items-center justify-end gap-1"
    data-test="storage-chip"
    @keydown="onKeydown"
  >
    <button
      type="button"
      class="inline-flex items-center rounded-full"
      aria-haspopup="menu"
      :aria-expanded="open"
      aria-label="Storage location"
      @click="open = !open"
    >
      <UiBadge v-if="!storage.target" tone="warn" data-test="chip-none">None chosen</UiBadge>
      <UiBadge v-else :tone="storage.target.mounted ? 'ok' : 'danger'" data-test="chip-target">
        {{ storage.target.name || storage.target.label || 'Storage' }}
        <template v-if="storage.target.mounted">
          · {{ formatBytes(storage.target.free) }} free</template
        >
        <template v-else> · offline</template>
        <UiIcon name="ChevronDown" :size="12" />
      </UiBadge>
    </button>
    <UiBadge
      v-if="backupText"
      :tone="storage.backup?.running ? 'accent' : 'warn'"
      data-test="chip-backup"
    >
      {{ backupText }}
    </UiBadge>
    <ul
      v-if="open"
      role="menu"
      class="absolute right-0 top-full z-20 mt-1 min-w-48 rounded-inner border border-camera-border bg-camera-surface p-1 text-left text-sm shadow-lg"
      data-test="chip-menu"
    >
      <li v-for="l in candidates" :key="l.id" role="none">
        <button
          type="button"
          role="menuitem"
          class="h-[var(--ctl-sm)] w-full rounded-control px-2 text-left hover:bg-camera-raised"
          :data-test="`switch-${l.id}`"
          @click="pick(l.id)"
        >
          {{ l.name || l.label || 'Storage' }}
        </button>
      </li>
      <li v-if="!candidates.length" class="px-2 py-1 text-camera-muted">No other mounted drive</li>
    </ul>
  </span>
</template>
