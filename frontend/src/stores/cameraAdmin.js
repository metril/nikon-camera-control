import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'
import { useConfigStore } from './config'

export const useCameraAdminStore = defineStore('cameraAdmin', () => {
  const clock = ref(null) // { data: DatetimeOut, fetchedAt: ms }
  const target = ref(null) // { value, choices }
  const lastError = ref(null)

  const fetchClock = () =>
    guard(lastError, async () => {
      const data = await api.getCameraDatetime()
      clock.value = { data, fetchedAt: Date.now() }
      return data
    })
  /** Set the camera clock from this device's clock and time zone. */
  const syncClock = () =>
    guard(lastError, async () => {
      // With an app time zone set the server picks its offset; otherwise use the browser's.
      const zoned = !!useConfigStore().config?.timezone
      const data = await api.setCameraDatetime({
        body: zoned
          ? { mode: 'host' }
          : { mode: 'host', utc_offset_minutes: -new Date().getTimezoneOffset() },
      })
      clock.value = { data, fetchedAt: Date.now() }
      return data
    })
  const fetchTarget = () =>
    guard(lastError, async () => (target.value = await api.getCaptureTarget()))
  const setTarget = (value) =>
    guard(lastError, async () => (target.value = await api.setCaptureTarget({ body: { value } })))

  /** Reload everything (camera connect); failures stay in lastError. */
  const refresh = () => Promise.allSettled([fetchClock(), fetchTarget()])
  function reset() {
    clock.value = target.value = null
  }

  return { clock, target, lastError, fetchClock, syncClock, fetchTarget, setTarget, refresh, reset }
})
