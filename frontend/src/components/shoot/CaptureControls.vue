<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import { useToastsStore } from '@/stores/toasts'
import UiButton from '@/components/ui/UiButton.vue'
import UiToggle from '@/components/ui/UiToggle.vue'
import UiText from '@/components/ui/UiText.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import NoTargetNotice from '@/components/shell/NoTargetNotice.vue'
import { useStorageStore } from '@/stores/storage'
import { isNoTarget } from '@/api'

const emit = defineEmits(['open-gallery', 'open-settings'])

const camera = useCameraStore()
const capture = useCaptureStore()
const files = useFilesStore()
const toasts = useToastsStore()
const storage = useStorageStore()

const download = ref(true)
const deleteAfter = ref(false)
const prefix = ref('')
const thumbs = ref({}) // path -> src
let gone = false
const releases = []
onUnmounted(() => {
  gone = true
  releases.splice(0).forEach((r) => r())
})

const busyReason = computed(() =>
  camera.leasedBy ? `Busy: ${String(camera.leasedBy).replace(/[-_]/g, ' ')} running` : '',
)
const noTarget = computed(() => storage.noTarget || isNoTarget(capture.lastError))
const canShoot = computed(
  () => camera.connected && !capture.inFlight && !camera.leasedBy && !noTarget.value,
)
const result = computed(() => capture.lastCapture)
const savedFiles = computed(() => result.value?.files || [])
const cardFiles = computed(() => result.value?.camera_files || [])

function body() {
  const p = prefix.value.trim()
  return {
    download: download.value,
    delete_from_camera: download.value && deleteAfter.value,
    filename_prefix: p || null,
  }
}

async function shoot() {
  if (!canShoot.value) return
  try {
    await capture.capture(body())
  } catch (e) {
    toasts.error(e)
  }
}
async function triggerOnly() {
  if (!canShoot.value) return
  try {
    await capture.trigger()
    toasts.info('Shutter triggered')
  } catch (e) {
    toasts.error(e)
  }
}

watch(
  savedFiles,
  (list) => {
    for (const f of list) {
      if (f.kind !== 'image' || thumbs.value[f.path]) continue
      files
        .acquireThumbnail(f.path, 160)
        .then((h) => {
          if (gone) return h.release()
          releases.push(h.release)
          thumbs.value = { ...thumbs.value, [f.path]: h.url }
        })
        .catch(() => {})
    }
  },
  { immediate: true },
)
</script>

<template>
  <section
    class="rounded-lg border border-camera-border bg-camera-surface p-4"
    aria-label="Capture"
  >
    <UiEmpty
      v-if="!camera.connected"
      title="Camera not connected"
      hint="Connect the camera to capture."
    >
      <template #actions>
        <UiButton variant="primary" size="sm" @click="camera.connect().catch(toasts.error)"
          >Connect</UiButton
        >
      </template>
    </UiEmpty>

    <div v-else class="flex flex-col gap-4">
      <div class="flex flex-col items-center gap-2">
        <UiButton
          variant="danger"
          class="!h-16 w-full max-w-xs !text-lg"
          :loading="capture.inFlight"
          :disabled="!canShoot"
          data-testid="capture-btn"
          @click="shoot"
          >{{ capture.inFlight ? 'Capturing...' : 'Capture' }}</UiButton
        >
        <p class="text-xs text-camera-muted">Press Space to capture</p>
        <NoTargetNotice v-if="noTarget" compact @open-settings="emit('open-settings')" />
        <p v-if="busyReason" class="text-sm text-camera-warning" role="status" aria-live="polite">
          {{ busyReason }}
        </p>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <UiToggle v-model="download" label="Download to server" />
        <UiToggle
          v-model="deleteAfter"
          label="Delete from card after download"
          :disabled="!download"
        />
        <UiText v-model="prefix" label="Filename prefix" :maxlength="40" placeholder="optional" />
        <div class="flex items-end">
          <UiButton :disabled="!canShoot" data-testid="trigger-btn" @click="triggerOnly"
            >Trigger only</UiButton
          >
        </div>
      </div>

      <div
        v-if="capture.lastError && !result && !noTarget"
        class="text-sm text-camera-error"
        aria-live="polite"
      >
        {{ capture.lastError.message }}
      </div>

      <div v-if="result" class="rounded border border-camera-border p-3" data-testid="last-capture">
        <div class="mb-2 flex items-center justify-between">
          <h3 class="text-sm font-medium">Last capture</h3>
          <UiButton size="sm" variant="ghost" @click="emit('open-gallery')">Open Gallery</UiButton>
        </div>
        <ul v-if="savedFiles.length" class="flex flex-wrap gap-3">
          <li v-for="f in savedFiles" :key="f.path" class="w-24 text-xs">
            <button
              type="button"
              class="block w-full overflow-hidden rounded border border-camera-border focus:outline-none focus:ring-2 focus:ring-camera-accent"
              :aria-label="`Open ${f.name} in Gallery`"
              @click="emit('open-gallery', f)"
            >
              <img
                v-if="thumbs[f.path]"
                :src="thumbs[f.path]"
                :alt="f.name"
                class="h-16 w-full object-cover"
              />
              <span
                v-else
                class="flex h-16 items-center justify-center uppercase text-camera-muted"
              >
                {{ f.kind }}
              </span>
            </button>
            <span class="mt-1 block truncate" :title="f.name">{{ f.name }}</span>
          </li>
        </ul>
        <ul v-else-if="cardFiles.length" class="text-xs text-camera-muted">
          <li v-for="f in cardFiles" :key="f.path || f.name">{{ f.name }} (on card)</li>
        </ul>
        <p v-else class="text-xs text-camera-muted">No files were reported.</p>
      </div>
    </div>
  </section>
</template>
