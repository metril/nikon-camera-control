import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { SETTING_FOR } from '@/components/shoot/exposure'
import { guard } from './helpers'

export const useSettingsStore = defineStore('settings', () => {
  const common = ref([]) // SettingOut[] (common group)
  const all = ref([]) // SettingOut[] (all settings, loaded on demand)
  const loading = ref(false)
  const lastError = ref(null)
  // name -> {latest, base, waiters, running}: one in-flight write per setting
  const queues = new Map()

  const find = (name) =>
    common.value.find((s) => s.name === name) || all.value.find((s) => s.name === name)
  const get = (name) => find(name)?.value

  function patchLocal(name, patch) {
    for (const list of [common.value, all.value]) {
      const i = list.findIndex((s) => s.name === name)
      if (i >= 0) list[i] = { ...list[i], ...patch }
    }
  }

  async function load(group) {
    loading.value = true
    try {
      return await guard(lastError, async () => {
        const items = await api.listSettings({ query: { group } })
        if (group === 'all') all.value = items
        else common.value = items
        return items
      })
    } finally {
      loading.value = false
    }
  }
  const fetchCommon = () => load('common')
  const fetchAll = () => load('all')

  /** Ask the camera to re-read its values, then reload what is shown. */
  async function refreshFromCamera() {
    await guard(lastError, () => api.refreshSettings())
    await fetchCommon()
    if (all.value.length) await fetchAll()
  }

  /**
   * Re-read just the exposure strip's widgets from the camera (one cheap read each) for bodies
   * that do not announce changes made on the body. Skips widgets with a write in flight.
   */
  async function refreshExposure() {
    const names = Object.values(SETTING_FOR)
      .map((cands) => cands.find((n) => common.value.some((s) => s.name === n)))
      .filter(Boolean)
    for (const name of names) {
      try {
        const out = await api.getSetting({ path: { name }, query: { fresh: true } })
        if (!queues.has(name) && out && typeof out === 'object') patchLocal(name, out)
      } catch {
        return // camera busy or gone: the next tick tries again
      }
    }
  }

  /**
   * Optimistic write. Rapid calls for the same setting coalesce: while a request is in flight
   * only the newest value is kept and sent next. On failure the last confirmed value is
   * restored and every pending caller's promise rejects with the ApiError.
   */
  function set(name, value) {
    let q = queues.get(name)
    if (!q) {
      q = { latest: value, base: get(name), event: null, sent: [], waiters: [], running: false }
      queues.set(name, q)
    } else {
      q.latest = value
    }
    patchLocal(name, { value })
    return new Promise((resolve, reject) => {
      q.waiters.push({ resolve, reject })
      if (!q.running) drain(name, q)
    })
  }

  async function drain(name, q) {
    q.running = true
    try {
      let out
      for (;;) {
        const sent = q.latest
        q.event = null
        q.sent.push(JSON.stringify(sent))
        out = await api.setSetting({ path: { name }, body: { value: sent } })
        // the camera's canonical value is the new rollback point for a later failed write
        q.base = out && typeof out === 'object' && 'value' in out ? out.value : sent
        if (q.latest === sent) break
      }
      queues.delete(name)
      lastError.value = null
      if (out && typeof out === 'object') patchLocal(name, out)
      if (q.event) patchLocal(name, { value: q.event.value }) // camera changed after our last write
      q.waiters.forEach((w) => w.resolve(out))
    } catch (e) {
      queues.delete(name)
      patchLocal(name, { value: q.event ? q.event.value : q.base })
      lastError.value = e
      q.waiters.forEach((w) => w.reject(e))
    }
  }

  // --- event handler
  function onSettingChanged({ name, value }) {
    const q = queues.get(name)
    if (q) {
      // each send is echoed at most once: consume it (and older, never-echoed sends) so a later
      // real change back to the same value is not mistaken for an echo
      const i = q.sent.indexOf(JSON.stringify(value))
      if (i >= 0) {
        q.sent.splice(0, i + 1)
        return
      }
      q.event = { value } // our own write is in flight; applied when the queue drains
      return
    }
    patchLocal(name, { value })
  }

  return {
    common,
    all,
    loading,
    lastError,
    get,
    find,
    fetchCommon,
    fetchAll,
    refreshFromCamera,
    refreshExposure,
    set,
    onSettingChanged,
  }
})
