import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useCameraStore } from './camera'
import { useEventsStore } from './events'
import { useSettingsStore } from './settings'
import { vi } from 'vitest'

describe('camera store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('clears everything on camera_disconnected', () => {
    const cam = useCameraStore()
    const ev = useEventsStore()
    // camera_connected triggers background refreshes; keep them off the network
    for (const [st, n] of [
      [cam, 'fetchStatus'],
      [cam, 'fetchBattery'],
      [useSettingsStore(), 'fetchCommon'],
    ])
      vi.spyOn(st, n).mockResolvedValue(null)
    ev.dispatch({ type: 'camera_connected', data: { model: 'D500', serial: '123' } })
    cam.battery = { level: '80', percent: 80 }
    cam.storage = { cards: [{}] }
    expect(cam.connected).toBe(true)
    expect(cam.model).toBe('D500')
    ev.dispatch({ type: 'camera_disconnected', data: { reason: 'usb' } })
    expect(cam.connected).toBe(false)
    expect(cam.state).toBe('disconnected')
    expect(cam.model).toBeNull()
    expect(cam.battery).toBeNull()
    expect(cam.storage).toBeNull()
  })

  it('camera_state to disconnected also clears; other states update', () => {
    const cam = useCameraStore()
    cam.onConnected({ model: 'D500', serial: '1' })
    cam.onCameraState({ state: 'liveview', previous: 'idle' })
    expect(cam.state).toBe('liveview')
    cam.onCameraState({ state: 'disconnected' })
    expect(cam.connected).toBe(false)
    expect(cam.model).toBeNull()
  })
})
