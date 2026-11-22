<script setup>
import UiCard from '@/components/ui/UiCard.vue'
import UiToggle from '@/components/ui/UiToggle.vue'

defineProps({ modelValue: Boolean, dirty: Boolean })
defineEmits(['update:modelValue'])
</script>

<template>
  <UiCard title="Demo camera">
    <UiToggle
      :model-value="modelValue"
      :label="`Use the simulated camera${dirty ? ' *' : ''}`"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <p class="mt-2 text-xs text-camera-muted">
      Lets you try the app without a camera. Takes effect on the next connect: disconnect and
      connect again after saving.
    </p>
  </UiCard>
</template>
