<script setup>
/**
 * Exposure strip: mode, shutter, aperture, ISO, EV (or Meter in M), WB, shots left, preset.
 * Tap a value to pick another one; A / S / I / E focus a value and [ ] step it.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'
import { useShootStore } from '@/stores/shoot'
import { useToastsStore } from '@/stores/toasts'
import { leaseOwner } from '@/labels'
import UiButton from '@/components/ui/UiButton.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import StripPicker from './StripPicker.vue'
import PresetsManager from './PresetsManager.vue'
import { GOVERNED, SETTING_FOR, formatValue, modeLetter, optionFor } from './exposure'

const emit = defineEmits(['navigate'])

const camera = useCameraStore()
const settings = useSettingsStore()
const presets = usePresetsStore()
const shoot = useShootStore()
const toasts = useToastsStore()

const root = ref(null)
const open = ref(null) // key of the cell whose picker is open
const saveOpen = ref(false)
const manageOpen = ref(false)

const on = computed(() => camera.connected)
const lockReason = computed(() => (camera.leasedBy ? `Busy: ${leaseOwner(camera.leasedBy)}` : ''))

/** The camera setting behind a cell (first name the camera knows). */
const settingFor = (key) => {
  for (const n of SETTING_FOR[key] || []) {
    const s = settings.find(n)
    if (s) return s
  }
  return null
}
const letter = computed(() => modeLetter(settingFor('mode')?.value))
const governed = computed(() => GOVERNED[letter.value] || [])
const choicesOf = (key) => settingFor(key)?.choices || []
const writable = (s) => !!s && s.writable && !s.readonly && !!s.choices?.length

const shotsLeft = computed(() => {
  const cards = camera.storage?.cards
  if (!cards?.length) return null
  return cards.reduce((n, c) => n + (c.free_images || 0), 0)
})
const meter = computed(() => {
  const n = Number(settings.get('lightmeter'))
  return Number.isFinite(n) ? n : null
})

const FULL = {
  mode: 'Mode',
  shutter: 'Shutter speed',
  aperture: 'Aperture',
  iso: 'ISO',
  comp: 'Exposure compensation',
  meter: 'Meter',
  wb: 'White balance',
  shots: 'Shots left',
  preset: 'Preset',
}
const SHORT = { comp: 'EV', wb: 'WB', shutter: 'Shutter' }

const cells = computed(() => {
  const keys = ['mode', 'shutter', 'aperture', 'iso', letter.value === 'M' ? 'meter' : 'comp']
  keys.push('wb', 'shots', 'preset')
  return keys.map((key) => {
    const s = settingFor(key)
    const auto = on.value && governed.value.includes(key)
    let value
    let editable = false
    let hint = ''
    let tone = ''
    if (key === 'shots') {
      value = shotsLeft.value == null ? '–' : shotsLeft.value.toLocaleString('en-GB')
      hint = 'Shots left on the card'
    } else if (key === 'meter') {
      value = meter.value == null ? '–' : formatValue('comp', Math.round(meter.value * 3) / 3)
      tone = meter.value > 0.2 ? 'pos' : meter.value < -0.2 ? 'neg' : ''
      hint = meter.value == null ? 'Not reported by this camera' : 'Light meter reading'
    } else if (key === 'preset') {
      value = shoot.appliedPreset || 'None'
      editable = true
    } else {
      value = formatValue(key, s?.value)
      editable = writable(s)
      if (!editable && s)
        hint = key === 'mode' ? 'Set on the camera mode dial' : 'Read-only on the camera'
    }
    if (auto) {
      editable = false
      hint = `Set automatically by mode ${letter.value}`
    }
    if (lockReason.value && key !== 'preset') editable = false
    if (lockReason.value) hint = lockReason.value
    return {
      key,
      label: SHORT[key] || FULL[key],
      full: FULL[key],
      value: on.value ? value : '–',
      auto,
      editable: on.value && editable,
      hint,
      tone,
    }
  })
})

// --- picker
const anchorEl = computed(() => root.value?.querySelector(`[data-k="${open.value}"]`) || null)
const pickerTitle = computed(() => FULL[open.value] || '')
const pickerOptions = computed(() => {
  const k = open.value
  if (k === 'preset') {
    const none = {
      value: '',
      label: 'None',
      sub: 'Keep the current settings',
      selected: !shoot.appliedPreset,
    }
    const list = presets.settingsPresets.map((p) => ({
      value: p.id,
      label: p.name,
      sub: p.description || `${Object.keys(p.values || {}).length} settings`,
      selected: p.name === shoot.appliedPreset,
    }))
    return [none, ...list]
  }
  const s = settingFor(k)
  return choicesOf(k).map((c) => optionFor(k, c, s?.value))
})
const pickerLocked = computed(() => {
  const c = cells.value.find((x) => x.key === open.value)
  if (!c || c.editable || open.value === 'preset') return ''
  return c.auto ? `Set by mode ${letter.value}` : c.hint
})

function openPicker(c) {
  if (open.value === c.key) return (open.value = null)
  if (!on.value) return
  if (c.key === 'preset' && !presets.items.length) presets.fetch().catch(() => {})
  open.value = c.key
}

async function change(key, value) {
  const s = settingFor(key)
  if (!s) return
  try {
    await settings.set(s.name, value)
    shoot.appliedPreset = null
  } catch (e) {
    toasts.error(`${FULL[key]}: ${e?.message || 'Could not change it'} (reverted)`)
  }
}
async function applyPreset(id) {
  if (!id) {
    shoot.appliedPreset = null
    return
  }
  const p = presets.items.find((x) => x.id === id)
  try {
    await presets.apply(id)
    shoot.appliedPreset = p?.name || null
    toasts.success(`Preset applied: ${p?.name || 'preset'}`)
    settings.fetchCommon().catch(() => {})
  } catch (e) {
    toasts.error(e)
  }
}
function onSelect(value) {
  const k = open.value
  open.value = null
  if (k === 'preset') applyPreset(value)
  else change(k, value)
}

// --- keyboard: focus a cell, step its value
const cellEl = (key) => root.value?.querySelector(`[data-k="${key}"]`)
function focusCell(key) {
  cellEl(key)?.focus()
}
function step(key, dir) {
  const c = cells.value.find((x) => x.key === key)
  const s = settingFor(key)
  if (!c?.editable || !s) return
  const list = s.choices
  const at = list.findIndex((x) => String(x) === String(s.value))
  const next = list[Math.max(0, Math.min(list.length - 1, (at < 0 ? 0 : at) + dir))]
  if (next !== undefined && String(next) !== String(s.value)) change(key, next)
}
function onKeydown(e) {
  if (e.key !== '[' && e.key !== ']') return
  const key = e.target?.closest?.('[data-k]')?.dataset.k
  if (!key) return
  e.preventDefault()
  e.stopPropagation()
  step(key, e.key === ']' ? 1 : -1)
}
defineExpose({ focusCell, step })

// --- settings load
function ensureLoaded() {
  if (camera.connected && !settings.common.length && !settings.loading)
    settings.fetchCommon().catch((e) => toasts.error(e))
}
watch(() => camera.connected, ensureLoaded)
onMounted(() => {
  ensureLoaded()
  if (!presets.items.length) presets.fetch().catch(() => {})
})
// Keep the focus on the cell after its picker closes and the strip re-renders.
watch(open, async (k, was) => {
  if (!k && was) {
    await nextTick()
    cellEl(was)?.focus({ preventScroll: true })
  }
})
</script>

<template>
  <div ref="root" class="strip" role="group" aria-label="Exposure" @keydown="onKeydown">
    <template v-for="c in cells" :key="c.key">
      <button
        v-if="c.editable"
        type="button"
        class="cell"
        :data-k="c.key"
        aria-haspopup="dialog"
        :aria-expanded="open === c.key"
        :aria-label="`${c.full}: ${c.value}`"
        :title="c.full"
        @click="openPicker(c)"
      >
        <span class="k">{{ c.label }}</span>
        <span class="vrow">
          <span class="v tabular-nums" :class="c.tone">{{ c.value }}</span>
        </span>
      </button>
      <div
        v-else
        class="cell ro"
        :class="{ off: !on }"
        :data-k="c.key"
        role="group"
        tabindex="0"
        :aria-label="`${c.full}: ${c.value}${c.auto ? ', set automatically' : ''}`"
        :title="c.hint ? `${c.full}. ${c.hint}` : c.full"
      >
        <span class="k">{{ c.label }}</span>
        <span class="vrow">
          <span class="v tabular-nums" :class="[c.tone, { autov: c.auto }]">{{ c.value }}</span>
          <span v-if="c.auto" class="auto" aria-hidden="true">AUTO</span>
        </span>
      </div>
    </template>

    <StripPicker
      v-if="open"
      :title="pickerTitle"
      :options="pickerOptions"
      :anchor="anchorEl"
      :locked-reason="pickerLocked"
      :two-line="open === 'mode' || open === 'preset'"
      :empty-text="open === 'preset' ? 'No presets yet.' : 'The camera lists no other values.'"
      @select="onSelect"
      @close="open = null"
    >
      <template v-if="open === 'preset'" #footer>
        <UiButton
          size="sm"
          variant="ghost"
          class="!justify-start"
          @click="((open = null), (saveOpen = true))"
        >
          <UiIcon name="Save" :size="16" /> Save current settings as preset…
        </UiButton>
        <UiButton
          size="sm"
          variant="ghost"
          class="!justify-start"
          @click="((open = null), (manageOpen = true))"
        >
          <UiIcon name="SlidersHorizontal" :size="16" /> Manage presets…
        </UiButton>
      </template>
    </StripPicker>
    <PresetsManager
      v-model:save-open="saveOpen"
      v-model:manage-open="manageOpen"
      @navigate="(...a) => emit('navigate', ...a)"
    />
  </div>
</template>

<style scoped>
.strip {
  display: flex;
  background: theme('colors.camera.surface');
  border: 1px solid theme('colors.camera.subtle');
  border-radius: theme('borderRadius.card');
  overflow: hidden;
}
.cell {
  flex: 1 1 0;
  min-width: 0;
  border: 0;
  background: none;
  text-align: left;
  padding: 12px 16px;
  display: grid;
  gap: 2px;
  cursor: pointer;
  position: relative;
  color: theme('colors.camera.text');
}
.cell + .cell {
  border-left: 1px solid theme('colors.camera.subtle');
}
.cell:hover:not(.ro) {
  background: theme('colors.camera.raised');
}
.cell:active:not(.ro) {
  background: theme('colors.camera.hover');
}
.cell[aria-expanded='true'] {
  background: theme('colors.camera.raised');
  box-shadow: inset 0 -2px 0 theme('colors.camera.accent');
}
.cell.ro {
  cursor: default;
}
.cell .k {
  font:
    500 10.5px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: theme('colors.camera.muted');
  white-space: nowrap;
}
.vrow {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.cell .v {
  font:
    500 20px/1.25 ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell .v.autov {
  color: theme('colors.camera.muted');
}
.cell.off .v {
  color: theme('colors.camera.faint');
}
.cell .v.neg {
  color: theme('colors.camera.cold');
}
.cell .v.pos {
  color: theme('colors.camera.warn');
}
.cell .auto {
  flex: none;
  display: inline-flex;
  align-items: center;
  height: 16px;
  padding: 0 4px;
  border: 1px solid theme('colors.camera.border');
  border-radius: 4px;
  font:
    500 9px ui-monospace,
    SFMono-Regular,
    Menlo,
    monospace;
  letter-spacing: 0.06em;
  color: theme('colors.camera.muted');
}
@media (max-width: 1000px) {
  .cell .auto {
    display: none;
  }
}
</style>
