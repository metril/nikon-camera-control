<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useToastsStore } from '@/stores/toasts'
import UiButton from '@/components/ui/UiButton.vue'
import UiText from '@/components/ui/UiText.vue'
import { leaseOwner, settingName } from '@/labels'
import SettingField from './SettingField.vue'

const GROUPS = [
  {
    title: 'Exposure',
    names: [
      'autoexposuremode',
      'expprogram',
      'iso',
      'f-number',
      'shutterspeed',
      'exposurecompensation',
      'meteringmode',
    ],
  },
  {
    title: 'Focus',
    names: ['focusmode', 'focusmode2', 'liveviewaffocus', 'focusmetermode', 'autofocusdrive'],
  },
  {
    title: 'Image',
    names: ['whitebalance', 'imagequality', 'imagesize', 'liveviewsize', 'colorspace'],
  },
]
const MAX_ROWS = 200

const camera = useCameraStore()
const settings = useSettingsStore()
const toasts = useToastsStore()

const pending = reactive({}) // name -> in-flight count
const errors = reactive({}) // name -> message
const refreshing = ref(false)
const showAll = ref(false)
const search = ref('')

const leaseReason = computed(() => (camera.leasedBy ? `Busy: ${leaseOwner(camera.leasedBy)}` : ''))
const visible = (s) => s.type !== 'section' && s.type !== 'button'

// Non-writable toggles are action widgets (autofocusdrive, bulb, movie ...): not useful as rows.
const commonVisible = (s) => visible(s) && !(s.type === 'toggle' && !s.writable)

const grouped = computed(() => {
  const list = settings.common.filter(commonVisible)
  const used = new Set()
  const out = GROUPS.map((g) => {
    const items = g.names.map((n) => list.find((s) => s.name === n)).filter(Boolean)
    items.forEach((s) => used.add(s.name))
    return { title: g.title, items }
  })
  out.push({ title: 'Other', items: list.filter((s) => !used.has(s.name)) })
  return out.filter((g) => g.items.length)
})

const filteredAll = computed(() => {
  const q = search.value.trim().toLowerCase()
  const list = settings.all.filter(visible)
  const hit = q
    ? list.filter((s) =>
        [s.name, s.label, s.path, s.value].some((x) =>
          String(x ?? '')
            .toLowerCase()
            .includes(q),
        ),
      )
    : list
  return hit
})
const shownAll = computed(() => filteredAll.value.slice(0, MAX_ROWS))

async function change(name, value) {
  pending[name] = (pending[name] || 0) + 1
  delete errors[name]
  try {
    await settings.set(name, value)
  } catch (e) {
    errors[name] = e?.message || 'Failed to change setting'
    if (pending[name] === 1) toasts.error(`${settingName(name)}: ${errors[name]} (reverted)`)
  } finally {
    pending[name]--
    if (pending[name] <= 0) delete pending[name]
  }
}

async function load(fn) {
  try {
    await fn()
  } catch (e) {
    toasts.error(e)
  }
}
async function refresh() {
  refreshing.value = true
  await load(() => settings.refreshFromCamera())
  refreshing.value = false
}
function ensureLoaded() {
  if (camera.connected && !settings.common.length && !settings.loading)
    load(() => settings.fetchCommon())
}
watch(() => camera.connected, ensureLoaded)
watch(showAll, (open) => {
  if (open && !settings.all.length) load(() => settings.fetchAll())
})
onMounted(ensureLoaded)
</script>

<template>
  <section class="flex flex-col gap-5" aria-label="Camera settings">
    <div class="flex items-center justify-between gap-2">
      <p v-if="!camera.connected" class="text-sm text-camera-muted">
        Connect the camera to change settings.
      </p>
      <span v-else />
      <UiButton
        size="sm"
        :loading="refreshing"
        :disabled="!camera.connected"
        data-testid="refresh"
        @click="refresh"
        >Refresh</UiButton
      >
    </div>

    <div v-if="camera.connected" class="flex flex-col gap-5">
      <p v-if="leaseReason" class="text-sm text-camera-warn" role="status" aria-live="polite">
        {{ leaseReason }}. Settings are locked.
      </p>
      <p v-if="!settings.common.length" class="text-sm text-camera-muted">
        {{ settings.loading ? 'Loading settings…' : 'No settings available.' }}
      </p>

      <div v-for="g in grouped" :key="g.title">
        <h3 class="eyebrow mb-2">
          {{ g.title }}
        </h3>
        <div class="grid gap-4 sm:grid-cols-2">
          <SettingField
            v-for="s in g.items"
            :key="s.name"
            :setting="s"
            :disabled="!!leaseReason"
            :reason="leaseReason"
            :saving="!!pending[s.name]"
            :error="errors[s.name] || ''"
            @change="change"
          />
        </div>
      </div>

      <div class="border-t border-camera-subtle pt-3">
        <UiButton
          variant="ghost"
          size="sm"
          class="-ml-2.5"
          :aria-expanded="showAll"
          data-testid="show-all"
          @click="showAll = !showAll"
          >{{ showAll ? 'Hide all settings' : 'Show all settings' }}</UiButton
        >
        <div v-if="showAll" class="mt-3 flex flex-col gap-3" data-testid="all-settings">
          <UiText v-model="search" label="Search settings" placeholder="Name, label or value" />
          <p v-if="settings.loading" class="text-sm text-camera-muted">Loading…</p>
          <div class="grid gap-4 sm:grid-cols-2">
            <SettingField
              v-for="s in shownAll"
              :key="s.path || s.name"
              :setting="s"
              :disabled="!!leaseReason"
              :reason="leaseReason"
              :saving="!!pending[s.name]"
              :error="errors[s.name] || ''"
              @change="change"
            />
          </div>
          <p v-if="filteredAll.length > MAX_ROWS" class="text-xs text-camera-muted">
            Showing {{ MAX_ROWS }} of {{ filteredAll.length }}; refine the search.
          </p>
        </div>
      </div>
    </div>
  </section>
</template>
