<script setup>
/** The "not protected" bar under the header: open mode, or protected by an API key alone. */
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import UiIcon from '@/components/ui/UiIcon.vue'

const auth = useAuthStore()
defineEmits(['open-security'])
const keyOnly = computed(() => auth.banner === 'key-only')
</script>

<template>
  <a
    v-if="auth.banner"
    href="#/settings?section=security"
    class="warn-bar"
    data-test="no-key-warning"
    @click.prevent="$emit('open-security')"
  >
    <UiIcon name="TriangleAlert" :size="16" />
    <span v-if="keyOnly">Only an API key protects the camera.</span>
    <span v-else>No password set. Anyone on the network can control the camera.</span>
    <u data-test="banner-link">{{ keyOnly ? 'Set an app password' : 'Settings › Security' }}</u>
  </a>
</template>

<style scoped>
.warn-bar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 16px;
  background: theme('colors.camera.raised');
  border-bottom: 1px solid theme('colors.camera.subtle');
  color: theme('colors.camera.warn');
  font-size: 13px;
  text-align: center;
}
html[data-layout='touch'] .warn-bar {
  min-height: 40px;
}
</style>
