import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import CameraAdminCard from './CameraAdminCard.vue'
import { api } from '@/api'
import { mountCard, button } from './testing'

vi.mock('@/api', () => ({
  api: {
    getCameraDatetime: vi.fn(),
    setCameraDatetime: vi.fn(),
    getCaptureTarget: vi.fn(),
    setCaptureTarget: vi.fn(),
  },
  downloadBlob: vi.fn(),
}))

const clock = (wall) => ({
  camera_wall_time: wall,
  camera_time: wall,
  camera_epoch: 0,
  host_time: wall,
  host_utc_offset_minutes: 0,
  offset_s: 0,
})

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-01-01T12:00:00Z'))
  vi.clearAllMocks()
  api.getCameraDatetime.mockResolvedValue(clock('2026-01-01T12:00:00'))
  api.getCaptureTarget.mockResolvedValue({
    value: 'Memory card',
    choices: ['Memory card', 'Internal memory'],
  })
})
afterEach(() => vi.useRealTimers())

describe('CameraAdminCard', () => {
  it('shows camera time, device time and the offset', async () => {
    const { wrapper } = mountCard(CameraAdminCard)
    await flushPromises()
    const off = -new Date().getTimezoneOffset() * 60000
    expect(wrapper.find('[data-testid=clock]').text()).toContain('2026-01-01 12:00:00')
    // the camera shows UTC wall time; the device wall time differs by the local offset
    const diffH = Math.round(-off / 3600000)
    if (diffH === 0) expect(wrapper.find('[data-testid=offset]').text()).toBe('in sync')
    else expect(wrapper.find('[data-testid=offset]').text()).toMatch(/ahead of|behind/)
  })

  it('clock sync sends mode host and the browser UTC offset', async () => {
    const { wrapper } = mountCard(CameraAdminCard)
    api.setCameraDatetime.mockResolvedValue(clock('2026-01-01T12:00:00'))
    await flushPromises()
    await button(wrapper, 'Sync camera clock to this device').trigger('click')
    await flushPromises()
    expect(api.setCameraDatetime).toHaveBeenCalledWith({
      body: { mode: 'host', utc_offset_minutes: -new Date().getTimezoneOffset() },
    })
  })

  it('changes the capture target', async () => {
    const { wrapper } = mountCard(CameraAdminCard)
    await flushPromises()
    api.setCaptureTarget.mockResolvedValue({
      value: 'Internal memory',
      choices: ['Memory card', 'Internal memory'],
    })
    await wrapper.find('select').setValue('Internal memory')
    await flushPromises()
    expect(api.setCaptureTarget).toHaveBeenCalledWith({ body: { value: 'Internal memory' } })
  })

  it('disables sync and target with the reason while leased or recording', async () => {
    const leased = mountCard(CameraAdminCard, { leasedBy: 'timelapse' })
    await flushPromises()
    expect(
      button(leased.wrapper, 'Sync camera clock to this device').attributes('disabled'),
    ).toBeDefined()
    expect(leased.wrapper.find('select').attributes('disabled')).toBeDefined()
    expect(leased.wrapper.find('[data-testid=target-reason]').text()).toBe('Busy: time-lapse')
    const rec = mountCard(CameraAdminCard, { state: 'recording', leasedBy: 'recording' })
    await flushPromises()
    expect(rec.wrapper.find('[data-testid=target-reason]').text()).toBe('Busy: recording')
  })

  it('shows an empty state when disconnected', () => {
    const { wrapper } = mountCard(CameraAdminCard, { connected: false })
    expect(wrapper.text()).toContain('Camera not connected')
    expect(api.getCameraDatetime).not.toHaveBeenCalled()
  })
})
