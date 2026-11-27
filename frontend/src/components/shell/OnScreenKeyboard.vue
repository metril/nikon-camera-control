<script setup>
/** Touch-layout text keyboard docked at the bottom of the viewport. Types into the focused field
 * through the composable, so v-model, input events and Enter behave like a physical keyboard. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiKey from '@/components/ui/UiKey.vue'
import UiIcon from '@/components/ui/UiIcon.vue'
import {
  attachOsk,
  closeOsk,
  oskBackspace,
  oskEnter,
  oskInsert,
  oskTarget,
} from '@/composables/useOnScreenKeyboard'

const LETTERS = ['qwertyuiop'.split(''), 'asdfghjkl'.split(''), 'zxcvbnm'.split('')]
const SYMBOLS = ['-/:;()$&@"'.split(''), '[]{}#%^*+='.split(''), ".,?!'_~".split('')]
const DIGITS = '1234567890'.split('')

const root = ref(null)
const symbols = ref(false)
const shift = ref(false)
const caps = ref(false)
let lastShift = 0

const open = computed(() => !!oskTarget.value)
const rows = computed(() => (symbols.value ? SYMBOLS : LETTERS))
const upper = computed(() => shift.value || caps.value)
const isPassword = computed(() => oskTarget.value?.type === 'password')
const shown = (k) => (!symbols.value && upper.value ? k.toUpperCase() : k)

function press(k) {
  oskInsert(shown(k))
  if (shift.value && !caps.value) shift.value = false
}
function toggleShift() {
  const now = Date.now()
  if (caps.value) caps.value = shift.value = false
  else if (shift.value && now - lastShift < 400) caps.value = true
  else shift.value = !shift.value
  lastShift = now
}

let delay = null
let tick = null
function stopRepeat() {
  clearTimeout(delay)
  clearInterval(tick)
  delay = tick = null
}
function startBack() {
  stopRepeat()
  oskBackspace()
  delay = setTimeout(() => (tick = setInterval(oskBackspace, 60)), 400)
}

function sync() {
  const el = oskTarget.value
  const h = open.value ? root.value?.offsetHeight || 0 : 0
  document.documentElement.style.setProperty('--osk-h', `${h}px`)
  if (open.value) document.documentElement.dataset.oskOpen = ''
  else delete document.documentElement.dataset.oskOpen
  if (el) {
    el.style.scrollMarginBottom = `${h + 16}px`
    el.scrollIntoView?.({ block: 'nearest' })
  }
}
let prev = null
watch(oskTarget, async (el) => {
  if (prev && prev !== el) prev.style.scrollMarginBottom = ''
  prev = el
  if (el) {
    symbols.value = shift.value = caps.value = false
  } else stopRepeat()
  await nextTick()
  sync()
})
watch([symbols, shift, caps], async () => {
  await nextTick()
  sync()
})

let detach = null
onMounted(() => (detach = attachOsk()))
onBeforeUnmount(() => {
  stopRepeat()
  detach?.()
})
</script>

<template>
  <div
    v-if="open"
    ref="root"
    class="osk"
    data-osk
    data-test="osk"
    role="group"
    aria-label="On-screen keyboard"
    @mousedown.prevent
    @pointerup="stopRepeat"
    @pointercancel="stopRepeat"
    @pointerleave="stopRepeat"
  >
    <div class="row">
      <UiKey v-for="d in DIGITS" :key="d" class="k" @click="oskInsert(d)">{{ d }}</UiKey>
    </div>
    <div v-for="(r, i) in rows" :key="i" class="row" :class="{ inset: i === 1 && !symbols }">
      <UiKey
        v-if="i === 2 && !symbols"
        class="wide"
        :variant="upper ? 'accent' : 'default'"
        :aria-pressed="upper"
        aria-label="Shift"
        data-test="osk-shift"
        @click="toggleShift"
        >{{ caps ? '⇪' : '⇧' }}</UiKey
      >
      <UiKey v-for="k in r" :key="k" class="k" :data-key="k" @click="press(k)">{{
        shown(k)
      }}</UiKey>
      <UiKey
        v-if="i === 2"
        class="wide"
        variant="quiet"
        aria-label="Backspace"
        data-test="osk-back"
        @pointerdown.prevent="startBack"
        @click.prevent
        >⌫</UiKey
      >
    </div>
    <div class="row">
      <UiKey class="wide" variant="quiet" data-test="osk-page" @click="symbols = !symbols">{{
        symbols ? 'ABC' : '123'
      }}</UiKey>
      <UiKey class="space" aria-label="Space" data-test="osk-space" @click="oskInsert(' ')">{{
        isPassword ? 'password' : 'space'
      }}</UiKey>
      <UiKey
        variant="accent"
        class="wide"
        aria-label="Enter"
        data-test="osk-enter"
        @click="oskEnter"
        >Enter</UiKey
      >
      <UiKey
        class="wide"
        variant="quiet"
        aria-label="Hide keyboard"
        data-test="osk-hide"
        @click="closeOsk({ blur: true })"
        ><UiIcon name="ChevronDown" :size="22"
      /></UiKey>
    </div>
  </div>
</template>

<style scoped>
.osk {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 70;
  display: grid;
  gap: 6px;
  max-height: 40vh;
  overflow-y: auto;
  padding: 8px max(8px, env(safe-area-inset-right, 0px)) max(8px, env(safe-area-inset-bottom, 0px))
    max(8px, env(safe-area-inset-left, 0px));
  background: theme('colors.camera.surface');
  border-top: 1px solid theme('colors.camera.border');
  box-shadow: 0 -12px 32px rgba(0, 0, 0, 0.45);
  touch-action: manipulation;
  user-select: none;
}
.row {
  display: flex;
  gap: 6px;
  justify-content: center;
}
.row.inset {
  padding: 0 28px;
}
.k {
  flex: 1 1 0;
  max-width: 96px;
  min-width: 0;
}
.wide {
  flex: 0 0 auto;
  min-width: 84px;
}
.space {
  flex: 1 1 auto;
  max-width: 520px;
  color: theme('colors.camera.muted');
  font-family: system-ui, sans-serif;
  font-size: 14px;
}
</style>
