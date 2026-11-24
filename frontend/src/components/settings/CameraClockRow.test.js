import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import CameraClockRow from './CameraClockRow.vue'
import { useCameraStore } from '@/stores/camera'
import { useCameraAdminStore } from '@/stores/cameraAdmin'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {} }))

function setup(connected) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const camera = useCameraStore()
  camera.connected = connected
  const admin = useCameraAdminStore()
  admin.refresh = vi.fn(async () => {})
  admin.syncClock = vi.fn(async () => {})
  return { w: mount(CameraClockRow, { global: { plugins: [pinia] } }), admin }
}

describe('CameraClockRow', () => {
  beforeEach(() => vi.clearAllMocks())

  it('explains why it is disabled while the camera is not connected', () => {
    const { w } = setup(false)
    expect(w.find('[data-test="clock-reason"]').text()).toContain('Connect the camera')
    expect(w.find('[data-test="clock-sync"]').attributes('disabled')).toBeDefined()
  })

  it('syncs the camera clock to this device', async () => {
    const { w, admin } = setup(true)
    await w.find('[data-test="clock-sync"]').trigger('click')
    await flushPromises()
    expect(admin.syncClock).toHaveBeenCalledTimes(1)
  })
})

describe('CameraClockRow app zone', () => {
  it('compares against the app time zone offset, not the browser', () => {
    const { w, admin } = setup(true)
    const now = Date.now()
    const wall = new Date(now + 14 * 3600000).toISOString().replace('Z', '')
    admin.clock = {
      data: { camera_wall_time: wall, camera_time: wall, app_utc_offset_minutes: 840 },
      fetchedAt: now,
    }
    return w.vm.$nextTick().then(() => {
      expect(w.find('[data-test="clock-summary"]').text()).toContain('In sync')
    })
  })
})
