<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import UiButton from './UiButton.vue'

const props = defineProps({
  variant: { type: String, default: 'secondary' },
  size: { type: String, default: 'md' },
  loading: Boolean,
  disabled: Boolean,
  type: { type: String, default: 'button' },
  confirmText: { type: String, default: 'Confirm?' },
})
const emit = defineEmits(['confirm'])

const armed = ref(false)
let timer = null
const disarm = () => {
  clearTimeout(timer)
  timer = null
  armed.value = false
}
function onClick() {
  if (armed.value) {
    disarm()
    emit('confirm')
    return
  }
  armed.value = true
  timer = setTimeout(disarm, 3000)
}
onBeforeUnmount(() => clearTimeout(timer))
const shownVariant = computed(() => (armed.value ? 'danger' : props.variant))
</script>

<template>
  <UiButton
    :variant="shownVariant"
    :size="size"
    :loading="loading"
    :disabled="disabled"
    :type="type"
    @click="onClick"
  >
    <template v-if="armed">{{ confirmText }}</template>
    <slot v-else />
  </UiButton>
</template>
