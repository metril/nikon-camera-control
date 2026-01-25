<script setup>
import { ref, onMounted, computed } from 'vue'

const files = ref([])
const loading = ref(false)
const error = ref(null)
const selectedFile = ref(null)

async function fetchFiles() {
  loading.value = true
  error.value = null

  try {
    const response = await fetch('/api/capture/files')
    if (!response.ok) throw new Error('Failed to fetch files')
    const data = await response.json()
    files.value = data.files || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function deleteFile(filename) {
  if (!confirm(`Delete ${filename}?`)) return

  try {
    const response = await fetch(`/api/capture/files/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    })
    if (!response.ok) throw new Error('Failed to delete file')
    await fetchFiles()
    if (selectedFile.value?.name === filename) {
      selectedFile.value = null
    }
  } catch (e) {
    console.error('Delete failed:', e)
  }
}

function getFileUrl(filename) {
  return `/api/capture/files/${encodeURIComponent(filename)}`
}

function formatFileSize(bytes) {
  if (!bytes) return '--'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) {
    bytes /= 1024
    i++
  }
  return `${bytes.toFixed(1)} ${units[i]}`
}

function formatDate(dateString) {
  if (!dateString) return '--'
  const date = new Date(dateString)
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function isImage(filename) {
  return /\.(jpg|jpeg|png|gif|bmp|tif|tiff)$/i.test(filename)
}

function selectFile(file) {
  selectedFile.value = file
}

function closePreview() {
  selectedFile.value = null
}

onMounted(fetchFiles)
</script>

<template>
  <div class="bg-camera-surface border border-camera-border rounded-lg overflow-hidden">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-2 border-b border-camera-border">
      <h2 class="font-medium">Captured Files</h2>
      <button
        @click="fetchFiles"
        :disabled="loading"
        class="text-xs text-camera-muted hover:text-camera-text transition-colors flex items-center gap-1"
      >
        <svg
          class="w-4 h-4"
          :class="loading ? 'animate-spin' : ''"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Refresh
      </button>
    </div>

    <!-- Content -->
    <div class="p-4">
      <!-- Error State -->
      <div v-if="error" class="text-center text-camera-error py-8">
        <p>{{ error }}</p>
        <button @click="fetchFiles" class="mt-2 text-sm text-camera-accent hover:underline">
          Try again
        </button>
      </div>

      <!-- Loading State -->
      <div v-else-if="loading && files.length === 0" class="text-center text-camera-muted py-8">
        <svg class="w-8 h-8 mx-auto animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <p class="mt-2">Loading files...</p>
      </div>

      <!-- Empty State -->
      <div v-else-if="files.length === 0" class="text-center text-camera-muted py-8">
        <svg class="w-12 h-12 mx-auto opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
        <p class="mt-2">No captured files yet</p>
      </div>

      <!-- File Grid -->
      <div v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <div
          v-for="file in files"
          :key="file.name"
          class="group relative bg-camera-bg rounded overflow-hidden cursor-pointer"
          @click="selectFile(file)"
        >
          <!-- Thumbnail -->
          <div class="aspect-square">
            <img
              v-if="isImage(file.name)"
              :src="getFileUrl(file.name)"
              :alt="file.name"
              class="w-full h-full object-cover"
              loading="lazy"
            />
            <div v-else class="w-full h-full flex items-center justify-center bg-camera-border">
              <svg class="w-8 h-8 text-camera-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
            </div>
          </div>

          <!-- Overlay with file info -->
          <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <p class="text-xs text-white truncate">{{ file.name }}</p>
            <p class="text-xs text-white/70">{{ formatFileSize(file.size) }}</p>
          </div>

          <!-- Delete button -->
          <button
            @click.stop="deleteFile(file.name)"
            class="absolute top-2 right-2 w-6 h-6 bg-camera-error/80 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-camera-error"
          >
            <svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Image Preview Modal -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-200"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-200"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="selectedFile"
          class="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
          @click="closePreview"
        >
          <div class="relative max-w-full max-h-full" @click.stop>
            <!-- Close button -->
            <button
              @click="closePreview"
              class="absolute -top-10 right-0 text-white hover:text-camera-accent transition-colors"
            >
              <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            <!-- Image -->
            <img
              v-if="isImage(selectedFile.name)"
              :src="getFileUrl(selectedFile.name)"
              :alt="selectedFile.name"
              class="max-w-full max-h-[80vh] object-contain rounded"
            />

            <!-- File info -->
            <div class="mt-4 text-center text-white">
              <p class="font-medium">{{ selectedFile.name }}</p>
              <p class="text-sm text-white/70 mt-1">
                {{ formatFileSize(selectedFile.size) }}
                <span v-if="selectedFile.modified"> &bull; {{ formatDate(selectedFile.modified) }}</span>
              </p>
              <a
                :href="getFileUrl(selectedFile.name)"
                download
                class="inline-flex items-center gap-2 mt-3 px-4 py-2 bg-camera-accent text-white rounded hover:bg-camera-accent/80 transition-colors"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Download
              </a>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
