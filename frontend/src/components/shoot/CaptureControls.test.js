import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import CaptureControls from './CaptureControls.vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useFilesStore } from '@/stores/files'
import { useToastsStore } from '@/stores/toasts'

function setup({ connected = true, leasedBy = null } = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const camera = useCameraStore()
  camera.connected = connected
  camera.leasedBy = leasedBy
  const capture = useCaptureStore()
  const files = useFilesStore()
  vi.spyOn(files, 'thumbnailSrc').mockImplementation(async (p) => `thumb:${p}`)
  return { pinia, camera, capture, files }
}
const mnt = (pinia) => mount(CaptureControls, { global: { plugins: [pinia] } })

describe('CaptureControls', () => {
  it('shows an empty state with Connect when disconnected', () => {
    const { pinia } = setup({ connected: false })
    const w = mnt(pinia)
    expect(w.text()).toContain('Camera not connected')
    expect(w.find('[data-testid="capture-btn"]').exists()).toBe(false)
  })

  it('calls the store once with the chosen options', async () => {
    const { pinia, capture } = setup()
    const spy = vi.spyOn(capture, 'capture').mockResolvedValue({ files: [], camera_files: [] })
    const w = mnt(pinia)
    await w.find('input').setValue('  shot_ ')
    await w.find('[data-testid="capture-btn"]').trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledTimes(1)
    expect(spy).toHaveBeenCalledWith({
      download: true,
      delete_from_camera: false,
      filename_prefix: 'shot_',
    })
  })

  it('shows an error toast on failure', async () => {
    const { pinia, capture } = setup()
    vi.spyOn(capture, 'capture').mockRejectedValue(new Error('Card full'))
    const w = mnt(pinia)
    await w.find('[data-testid="capture-btn"]').trigger('click')
    await flushPromises()
    const t = useToastsStore().items.at(-1)
    expect(t).toMatchObject({ kind: 'error', message: 'Card full' })
    expect(w.find('[data-testid="last-capture"]').exists()).toBe(false)
  })

  it('disables capture while in flight and when leased by another feature', async () => {
    const { pinia, capture, camera } = setup()
    const w = mnt(pinia)
    capture.inFlight = true
    await w.vm.$nextTick()
    expect(w.find('[data-testid="capture-btn"]').attributes('disabled')).toBeDefined()
    capture.inFlight = false
    camera.leasedBy = 'timelapse'
    await w.vm.$nextTick()
    expect(w.find('[data-testid="capture-btn"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('Busy: timelapse running')
  })

  it('renders RAW+JPEG results from the store only (no duplicate state)', async () => {
    const { pinia, capture } = setup()
    capture.lastCapture = {
      files: [
        { name: 'a.jpg', path: 's/a.jpg', size: 1, kind: 'image' },
        { name: 'a.nef', path: 's/a.nef', size: 2, kind: 'raw' },
      ],
      camera_files: [],
    }
    const w = mnt(pinia)
    await flushPromises()
    expect(w.findAll('li')).toHaveLength(2)
    expect(w.find('img').attributes('src')).toBe('thumb:s/a.jpg')
    await w.find('button[aria-label="Open a.jpg in Gallery"]').trigger('click')
    expect(w.emitted('open-gallery')).toBeTruthy()
  })

  it('trigger-only calls trigger', async () => {
    const { pinia, capture } = setup()
    const spy = vi.spyOn(capture, 'trigger').mockResolvedValue()
    const w = mnt(pinia)
    await w.find('[data-testid="trigger-btn"]').trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
