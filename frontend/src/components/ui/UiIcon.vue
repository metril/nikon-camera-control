<script setup>
/** Lucide icon, inline-flex centred. `name` is a PascalCase export of src/icons.js (e.g. 'Camera'). */
import { computed } from 'vue'
import * as icons from '@/icons'

const props = defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 18 },
  /** Accessible label; without it the icon is decorative (aria-hidden). */
  label: { type: String, default: '' },
})
const comp = computed(() => icons[props.name] || icons.Circle)
</script>

<template>
  <span
    class="inline-flex flex-none items-center justify-center"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <component :is="comp" :size="size" :stroke-width="1.75" />
  </span>
</template>
