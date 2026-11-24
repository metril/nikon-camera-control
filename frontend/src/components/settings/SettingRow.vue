<script setup>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
  dirty: Boolean,
  error: { type: String, default: '' },
  /** Toggles keep their natural size; every other control fills the column. */
  natural: Boolean,
})
</script>

<template>
  <div
    class="grid grid-cols-1 items-center gap-x-4 gap-y-2 border-b border-camera-subtle py-3 first:pt-0 last:border-b-0 last:pb-0 min-[621px]:grid-cols-[minmax(0,1fr)_minmax(240px,260px)]"
    :data-dirty="dirty || undefined"
  >
    <div class="grid min-w-0 gap-0.5">
      <b class="flex items-center gap-2 text-sm font-medium">
        {{ title }}
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
