<script setup>
import { computed, inject, onBeforeUnmount, ref, watchEffect } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  dirty: Boolean,
  error: { type: String, default: '' },
  /** Toggles keep their natural size; every other control fills the column. */
  natural: Boolean,
  /** Small labels next to the title (e.g. KIOSK); also searchable. */
  tags: { type: Array, default: () => [] },
})
const query = inject('settingsQuery', ref(''))
const section = inject('settingsSection', null)
const match = computed(() => {
  const q = query.value
  if (!q) return true
  const hay =
    `${props.title} ${props.description} ${props.tags.join(' ')} ${section?.title() ?? ''}`.toLowerCase()
  return q.split(/\s+/).every((w) => hay.includes(w))
})
const key = Symbol('row')
watchEffect(() => section?.set(key, match.value))
onBeforeUnmount(() => section?.del(key))
</script>

<template>
  <div
    v-show="match"
    class="grid grid-cols-1 items-center gap-x-4 gap-y-2 border-b border-camera-subtle py-3.5 first:pt-0 last:border-b-0 last:pb-0 min-[621px]:grid-cols-[minmax(0,1fr)_minmax(260px,380px)]"
    :data-dirty="dirty || undefined"
  >
    <div class="grid min-w-0 gap-0.5">
      <b class="flex items-center gap-2 text-sm font-medium">
        {{ title }}
        <span
          v-for="t in tags"
          :key="t"
          class="rounded-full border border-camera-border px-[7px] [html[data-layout=touch]_&]:hidden py-px font-mono text-[11px] font-medium uppercase tracking-[.06em] text-camera-muted"
          data-test="row-tag"
          >{{ t }}</span
        >
        <span
          v-if="dirty"
          role="img"
          aria-label="Unsaved change"
          title="Unsaved change"
          class="inline-block h-[7px] w-[7px] rounded-full bg-camera-accent"
          data-test="dirty-dot"
        />
      </b>
      <span v-if="description" class="text-[12.5px] text-camera-muted">{{ description }}</span>
      <span v-if="$slots.note" class="text-[12.5px] text-camera-muted"><slot name="note" /></span>
    </div>
    <div class="flex min-w-0 flex-col gap-1">
      <div
        class="flex min-w-0"
        :class="natural ? 'justify-start' : '[&>*]:w-full [&_label]:sr-only'"
      >
        <slot />
      </div>
      <p v-if="error" class="text-xs text-camera-danger" role="alert" data-test="field-error">
        {{ error }}
      </p>
    </div>
  </div>
</template>
