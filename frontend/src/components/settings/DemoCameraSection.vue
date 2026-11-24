<script setup>
import UiToggle from '@/components/ui/UiToggle.vue'
import SettingsSection from './SettingsSection.vue'
import SettingRow from './SettingRow.vue'

defineProps({ modelValue: Boolean, dirty: Boolean })
defineEmits(['update:modelValue'])
</script>

<template>
  <SettingsSection title="Demo camera" data-section="demo_camera">
    <SettingRow
      title="Use the simulated camera"
      description="Lets you try the app without a camera. Takes effect on the next connect: disconnect and connect again after saving."
      :dirty="dirty"
      natural
    >
      <UiToggle
        :model-value="modelValue"
        aria-label="Use the simulated camera"
        @update:model-value="$emit('update:modelValue', $event)"
      />
    </SettingRow>
  </SettingsSection>
</template>
