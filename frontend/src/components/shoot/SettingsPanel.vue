<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useToastsStore } from '@/stores/toasts'
import UiButton from '@/components/ui/UiButton.vue'
import UiText from '@/components/ui/UiText.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
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
  { title: 'Focus', names: ['focusmode', 'focusmode2', 'focusmetermode', 'autofocusdrive'] },
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

const leaseReason = computed(() =>
  camera.leasedBy ? `Busy: ${String(camera.leasedBy).replace(/[-_]/g, ' ')} running` : '',
)
const visible = (s) => s.type !== 'section' && s.type !== 'button'

const grouped = computed(() => {
  const list = settings.common.filter(visible)
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
    if (pending[name] === 1) toasts.error(`${name}: ${errors[name]} (reverted)`)
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
  <section
    class="rounded-lg border border-camera-border bg-camera-surface"
    aria-label="Camera settings"
  >
    <header class="flex items-center justify-between border-b border-camera-border px-4 py-2">
      <h2 class="font-medium">Camera Settings</h2>
      <UiButton
        size="sm"
        :loading="refreshing"
        :disabled="!camera.connected"
        data-testid="refresh"
        @click="refresh"
        >Refresh</UiButton
      >
    </header>

    <UiEmpty
      v-if="!camera.connected"
      class="p-4"
      title="Camera not connected"
      hint="Connect the camera to change settings."
    >
      <template #actions>
        <UiButton variant="primary" size="sm" @click="camera.connect().catch(toasts.error)"
          >Connect</UiButton
        >
      </template>
    </UiEmpty>

    <div v-else class="flex flex-col gap-5 p-4">
      <p v-if="leaseReason" class="text-sm text-camera-warning" role="status" aria-live="polite">
        {{ leaseReason }} - settings are locked.
      </p>
      <p v-if="!settings.common.length" class="text-sm text-camera-muted">
        {{ settings.loading ? 'Loading settings...' : 'No settings available.' }}
      </p>

      <div v-for="g in grouped" :key="g.title">
        <h3 class="mb-2 text-xs font-semibold uppercase tracking-wide text-camera-muted">
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

      <div class="border-t border-camera-border pt-3">
        <UiButton
          variant="ghost"
          size="sm"
          :aria-expanded="showAll"
          data-testid="show-all"
          @click="showAll = !showAll"
          >{{ showAll ? 'Hide all settings' : 'Show all settings' }}</UiButton
        >
        <div v-if="showAll" class="mt-3 flex flex-col gap-3" data-testid="all-settings">
          <UiText v-model="search" label="Search settings" placeholder="name, label or value" />
          <p v-if="settings.loading" class="text-sm text-camera-muted">Loading...</p>
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
