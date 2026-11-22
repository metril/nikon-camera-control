<script setup>
defineProps({ size: { type: String, default: 'md' } })
</script>

<template>
  <svg
    class="inline-block animate-spin motion-reduce:animate-none"
    :class="size === 'sm' ? 'h-4 w-4' : size === 'lg' ? 'h-8 w-8' : 'h-5 w-5'"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25" />
    <path d="M12 2a10 10 0 0110 10" stroke="currentColor" stroke-width="3" stroke-linecap="round" />
  </svg>
</template>
