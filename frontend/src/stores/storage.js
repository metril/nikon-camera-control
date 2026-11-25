import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'
import { useJobsStore } from './jobs'

export const useStorageStore = defineStore('storage', () => {
  const locations = ref([])
  const targetId = ref(null)
  const backupIds = ref([])
  const backup = ref(null) // BackupStatusOut / backup_status event
  const loaded = ref(false)
  const lastError = ref(null)

  const target = computed(() => locations.value.find((l) => l.id === targetId.value) || null)
  /** True only once the server confirmed there is no target (never while still loading). */
  const noTarget = computed(() => loaded.value && !targetId.value)
  const mounted = computed(() => locations.value.filter((l) => l.mounted))

  const apply = (out) => {
    locations.value = out.locations
    targetId.value = out.target_id ?? null
    backupIds.value = out.backup_ids || []
    loaded.value = true
    return out
  }
  const fetch = () => guard(lastError, async () => apply(await api.listLocations()))
  const fetchBackup = () =>
    guard(lastError, async () => (backup.value = await api.getBackupStatus()))
  const refresh = () => Promise.all([fetch(), fetchBackup()])

  const path = (id) => ({ path: { location_id: id } })
  const act = (fn) =>
    guard(lastError, async () => {
      const r = await fn()
      await fetch()
      return r
    })
  const mount = (id) => act(() => api.mountLocation(path(id)))
  const unmount = (id) => act(() => api.unmountLocation(path(id)))

  const add = (body) => act(() => api.addLocation({ body }))
  const remove = (id) => act(() => api.deleteLocation(path(id)))
  const testSmb = (body) => guard(lastError, () => api.testSmbLocation({ body }))
  const setTarget = (id) => act(() => api.setStorageTarget({ body: { id } }))
  const setBackups = (ids) => act(() => api.setStorageBackups({ body: { ids } }))
  const runBackup = () =>
    guard(lastError, async () => {
      const r = await api.runBackup()
      await fetchBackup().catch(() => {})
      return r
    })
  const toJob = async (p) => {
    const job = await p
    useJobsStore().upsert(job)
    return job
  }
  const check = (id) => guard(lastError, () => toJob(api.checkLocation(path(id))))
  const formatDisk = (disk, body) =>
    guard(lastError, () => toJob(api.formatDisk({ path: { disk }, body })))
  const offload = (body) => guard(lastError, () => toJob(api.startOffload({ body })))
  const verify = (body = {}) => guard(lastError, () => toJob(api.startVerify({ body })))

  const onLocationsChanged = () => fetch().catch(() => {})
  const onBackupStatus = (data) => (backup.value = { ...(backup.value || {}), ...data })

  return {
    locations,
    targetId,
    backupIds,
    backup,
    loaded,
    lastError,
    target,
    noTarget,
    mounted,
    fetch,
    fetchBackup,
    refresh,
    mount,
    unmount,
    check,
    formatDisk,
    add,
    remove,
    testSmb,
    setTarget,
    setBackups,
    runBackup,
    offload,
    verify,
    onLocationsChanged,
    onBackupStatus,
  }
})
