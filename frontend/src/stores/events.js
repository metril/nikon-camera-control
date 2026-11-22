import { defineStore } from 'pinia'
import { ref, computed, shallowRef, watch } from 'vue'
import { createEventSocket } from '@/api'
import { useCameraStore } from './camera'
import { useSettingsStore } from './settings'
import { useCaptureStore } from './capture'
import { useJobsStore } from './jobs'
import { useTimelapseStore } from './timelapse'
import { useLiveViewStore } from './liveview'
import { useRecordingStore } from './recording'
import { useBulbStore } from './bulb'
import { useFocusStore } from './focus'
import { useConfigStore } from './config'
import { useVideosStore } from './videos'
import { useToastsStore } from './toasts'
import { useAuthStore } from './auth'

/** Background refresh: failures land in the store's lastError; nothing to await or throw. */
const bg = (p) => p?.catch?.(() => {})

/**
 * The one place that turns server events {type, ts, data} into store updates.
 * Payload keys: docs/API.md "Events".
 */
export const useEventsStore = defineStore('events', () => {
  const sock = shallowRef(null)
  /** connecting | open | closed | unauthorized */
  const status = computed(() => (sock.value ? sock.value.status.value : 'closed'))
  const lastEventAt = ref(null)
  let stopWatch = null

  function dispatch(evt) {
    const { type, data = {}, ts } = evt || {}
    if (!type) return
    lastEventAt.value = ts ?? null
    const camera = useCameraStore()
    switch (type) {
      case 'camera_state':
        return camera.onCameraState(data)
      case 'camera_connected':
        camera.onConnected(data)
        bg(camera.fetchStatus())
        bg(camera.fetchBattery())
        bg(useSettingsStore().fetchCommon())
        return
      case 'camera_disconnected':
        camera.onDisconnected(data)
        useLiveViewStore().reset()
        useFocusStore().clear()
        return
      case 'battery':
        return camera.onBattery(data)
      case 'setting_changed':
        return useSettingsStore().onSettingChanged(data)
      case 'capture_started':
        useBulbStore().onStarted(data)
        return useCaptureStore().onStarted(data)
      case 'capture_complete':
        useBulbStore().onComplete(data)
        return useCaptureStore().onComplete(data)
      case 'liveview_started':
        return useLiveViewStore().onStarted(data)
      case 'liveview_stopped':
        return useLiveViewStore().onStopped(data)
      case 'recording_started':
        return useRecordingStore().onStarted(data)
      case 'recording_stopped':
        return useRecordingStore().onStopped(data)
      case 'job_created':
      case 'job_progress':
      case 'job_completed':
      case 'job_failed':
      case 'job_cancelled':
        useJobsStore().onJobEvent(data)
        if (type === 'job_completed' && data.job?.kind?.includes('video'))
          bg(useVideosStore().fetch())
        return
      case 'config_changed':
        return useConfigStore().onChanged(data)
      case 'error':
        return useToastsStore().error(data.message || data.code || 'Error')
      default:
        if (type.startsWith('timelapse_')) return useTimelapseStore().onEvent(type, data)
    }
  }

  /** Re-sync everything that events cannot replay (called on every (re)connect). */
  function resync() {
    bg(useCameraStore().fetchStatus())
    bg(useSettingsStore().fetchCommon())
    bg(useJobsStore().fetch())
    bg(useTimelapseStore().fetchStatus())
    bg(useLiveViewStore().fetchStatus())
    bg(useRecordingStore().fetchStatus())
  }

  function start() {
    if (sock.value) return
    sock.value = createEventSocket({ onEvent: dispatch, onOpen: resync })
    sock.value.start()
    useTimelapseStore().startPolling()
    // A new/changed API key needs a fresh socket handshake.
    stopWatch = watch(
      () => useAuthStore().apiKey,
      () => sock.value?.restart(),
    )
  }

  /** Reconnect now (e.g. after the key was entered). */
  function restart() {
    sock.value?.restart()
  }

  function stop() {
    stopWatch?.()
    stopWatch = null
    sock.value?.close()
    sock.value = null
    useTimelapseStore().stopPolling()
  }

  return { status, lastEventAt, dispatch, resync, start, restart, stop }
})
