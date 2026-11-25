import { describe, it, expect, beforeEach } from 'vitest'
import { createTestingPinia } from '@pinia/testing'
import { vi } from 'vitest'
import { useEventsStore } from './events'
import { useCameraStore } from './camera'
import { useSettingsStore } from './settings'
import { useJobsStore } from './jobs'
import { useTimelapseStore } from './timelapse'
import { useCaptureStore } from './capture'
import { useConfigStore } from './config'
import { useToastsStore } from './toasts'
import { useRecordingStore } from './recording'
import { usePresetsStore } from './presets'
import { clearCameraPreviews } from '@/components/gallery/cameraPreviews'

vi.mock('@/components/gallery/cameraPreviews', () => ({ clearCameraPreviews: vi.fn() }))

const stub = (store, ...names) =>
  names.forEach((n) => vi.spyOn(store, n).mockImplementation(() => {}))

describe('event dispatcher', () => {
  let ev
  beforeEach(() => {
    createTestingPinia({ stubActions: false, createSpy: vi.fn })
    ev = useEventsStore()
    stub(useCameraStore(), 'onCameraState', 'onBattery')
    stub(useSettingsStore(), 'onSettingChanged')
    stub(useCaptureStore(), 'onStarted')
    stub(useRecordingStore(), 'onStopped')
    stub(useConfigStore(), 'onChanged')
    stub(useJobsStore(), 'onJobEvent')
    stub(useTimelapseStore(), 'onEvent')
    stub(useToastsStore(), 'error')
    stub(usePresetsStore(), 'refetch')
  })

  it('routes events to the owning stores', () => {
    ev.dispatch({ type: 'camera_state', data: { state: 'idle' } })
    expect(useCameraStore().onCameraState).toHaveBeenCalledWith({ state: 'idle' })
    ev.dispatch({ type: 'battery', data: { level: '50' } })
    expect(useCameraStore().onBattery).toHaveBeenCalledWith({ level: '50' })
    ev.dispatch({ type: 'setting_changed', data: { name: 'iso', value: 1 } })
    expect(useSettingsStore().onSettingChanged).toHaveBeenCalledWith({ name: 'iso', value: 1 })
    ev.dispatch({ type: 'capture_started', data: { bulb: false } })
    expect(useCaptureStore().onStarted).toHaveBeenCalled()
    ev.dispatch({ type: 'recording_stopped', data: { reason: 'user' } })
    expect(useRecordingStore().onStopped).toHaveBeenCalledWith({ reason: 'user' })
    ev.dispatch({ type: 'config_changed', data: { config: {}, restart_required: ['x'] } })
    expect(useConfigStore().onChanged).toHaveBeenCalled()
  })

  it('drops cached card previews when the camera goes away or the card changes', () => {
    clearCameraPreviews.mockClear()
    ev.dispatch({ type: 'storage_changed', data: { cards: 1 } })
    expect(clearCameraPreviews).toHaveBeenCalledTimes(1)
    ev.dispatch({ type: 'camera_disconnected', data: {} })
    expect(clearCameraPreviews).toHaveBeenCalledTimes(2)
  })

  it('routes every job_* and timelapse_* event', () => {
    for (const t of ['job_created', 'job_progress', 'job_completed', 'job_failed', 'job_cancelled'])
      ev.dispatch({ type: t, data: { job: { id: 'j', kind: 'x' } } })
    expect(useJobsStore().onJobEvent).toHaveBeenCalledTimes(5)
    ev.dispatch({ type: 'timelapse_frame', data: { frames_done: 3 } })
    expect(useTimelapseStore().onEvent).toHaveBeenCalledWith('timelapse_frame', { frames_done: 3 })
  })

  it('presets_changed refreshes the presets store', () => {
    ev.dispatch({ type: 'presets_changed', data: { action: 'created', id: 'p', kind: 'settings' } })
    expect(usePresetsStore().refetch).toHaveBeenCalled()
  })

  it('error events become toasts; unknown/malformed events are ignored', () => {
    ev.dispatch({ type: 'error', data: { message: 'boom', code: 'X' } })
    expect(useToastsStore().error).toHaveBeenCalledWith({
      message: 'boom',
      code: 'X',
      details: undefined,
    })
    expect(() => {
      ev.dispatch({ type: 'who_knows', data: {} })
      ev.dispatch(null)
      ev.dispatch({})
    }).not.toThrow()
  })
})
