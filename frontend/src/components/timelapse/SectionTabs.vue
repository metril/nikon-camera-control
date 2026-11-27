<script setup>
/** Tab strip for the touch layout. Panels stay mounted (v-show) as `tl-<name>-panel-<id>`. */
const props = defineProps({
  modelValue: { type: String, required: true },
  /** [{ id, label }] */
  tabs: { type: Array, required: true },
  /** Names the strip and prefixes the ids. */
  name: { type: String, required: true },
  label: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
const tabId = (id) => `tl-${props.name}-tab-${id}`
const panelId = (id) => `tl-${props.name}-panel-${id}`

function onKey(e) {
  const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
  if (!step) return
  e.preventDefault()
  const i = props.tabs.findIndex((t) => t.id === props.modelValue)
  const next = props.tabs[(i + step + props.tabs.length) % props.tabs.length]
  emit('update:modelValue', next.id)
  document.getElementById(tabId(next.id))?.focus()
}
</script>

<template>
  <div
    role="tablist"
    :aria-label="label"
    class="flex flex-none gap-1 border-b border-camera-border px-2"
    @keydown="onKey"
  >
    <button
      v-for="t in tabs"
      :id="tabId(t.id)"
      :key="t.id"
      type="button"
      role="tab"
      :aria-selected="modelValue === t.id"
      :aria-controls="panelId(t.id)"
      :tabindex="modelValue === t.id ? 0 : -1"
      class="h-11 border-b-2 px-4 text-[15px] font-medium transition-colors"
      :class="
        modelValue === t.id
          ? 'border-camera-accent text-camera-text'
          : 'border-transparent text-camera-muted hover:text-camera-text'
      "
      @click="emit('update:modelValue', t.id)"
    >
      {{ t.label }}
    </button>
  </div>
</template>
