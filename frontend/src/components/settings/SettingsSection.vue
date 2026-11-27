<script setup>
import { computed, inject, onBeforeUnmount, provide, reactive, ref, watchEffect } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
// While searching, sections show a small heading and hide when none of their rows match.
const query = inject('settingsQuery', ref(''))
const hits = inject('settingsHits', null)
const rows = reactive(new Map())
provide('settingsSection', {
  title: () => props.title,
  set: (k, v) => rows.set(k, v),
  del: (k) => rows.delete(k),
})
const searching = computed(() => !!query.value)
const empty = computed(() => searching.value && ![...rows.values()].some(Boolean))
const id = Symbol('section')
watchEffect(() => hits?.set(id, !empty.value))
onBeforeUnmount(() => hits?.delete(id))
</script>

<template>
  <section v-show="!empty">
    <component
      :is="searching ? 'h3' : 'h2'"
      :class="searching ? 'eyebrow mb-1 mt-3' : 'mt-3 text-lg font-semibold'"
    >
      {{ title }}
    </component>
    <p v-if="subtitle && !searching" class="mt-0.5 text-[12.5px] text-camera-muted">
      {{ subtitle }}
    </p>
    <div class="mt-2"><slot /></div>
  </section>
</template>
