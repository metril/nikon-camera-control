import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

export const usePresetsStore = defineStore('presets', () => {
  const items = ref([])
  const warning = ref(null)
  const lastError = ref(null)

  async function fetch(kind) {
    return guard(lastError, async () => {
      const out = await api.listPresets({ query: kind ? { kind } : {} })
      items.value = out.items
      warning.value = out.warning ?? null
      return out
    })
  }
  const refetch = () => fetch().catch(() => {})
  async function create(body) {
    const p = await guard(lastError, () => api.createPreset({ body }))
    await refetch()
    return p
  }
  async function update(id, body) {
    const p = await guard(lastError, () => api.updatePreset({ path: { preset_id: id }, body }))
    await refetch()
    return p
  }
  async function remove(id) {
    await guard(lastError, () => api.deletePreset({ path: { preset_id: id } }))
    items.value = items.value.filter((p) => p.id !== id)
  }
  const apply = (id) => guard(lastError, () => api.applyPreset({ path: { preset_id: id } }))
  async function fromCamera(body) {
    const p = await guard(lastError, () => api.createPresetFromCamera({ body }))
    await refetch()
    return p
  }
  const exportAll = () => guard(lastError, () => api.exportPresets())
  async function importPresets(body) {
    const r = await guard(lastError, () => api.importPresets({ body }))
    await refetch()
    return r
  }

  return {
    items,
    warning,
    lastError,
    fetch,
    create,
    update,
    remove,
    apply,
    fromCamera,
    exportAll,
    importPresets,
  }
})
