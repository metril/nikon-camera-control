import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import CaptureSide from './CaptureSide.vue'
import { useBulbStore } from '@/stores/bulb'
import { useCaptureStore } from '@/stores/capture'
import { useShootStore } from '@/stores/shoot'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'
import { mountCard, button } from './testing'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {}, downloadBlob: vi.fn() }))

let wrapper
function setup(opts) {
  const r = mountCard(CaptureSide, {
    ...opts,
    attachTo: document.body,
    setup: () => {
      useBulbStore().fetchStatus = vi.fn().mockResolvedValue()
    },
  })
  wrapper = r.wrapper
  return r
}
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ''
})
const shutter = () => wrapper.find('[data-testid="capture-btn"]')

describe('CaptureSide', () => {
  it('shows Single, Bracket, Bulb and Stack above a shutter that says what it will do', async () => {
    setup()
    const modes = wrapper.findAll('[aria-label="Capture mode"] button').map((b) => b.text())
    expect(modes).toEqual(['Single', 'Bracket', 'Bulb', 'Stack'])
    expect(shutter().attributes('aria-label')).toBe('Capture')
    await button(wrapper, 'Bracket').trigger('click')
    expect(wrapper.find('[data-testid="shutter-label"]').text()).toBe('Capture 3 frames')
    await button(wrapper, 'Bulb').trigger('click')
    expect(wrapper.find('[data-testid="shutter-label"]').text()).toBe('Open shutter')
    await button(wrapper, 'Stack').trigger('click')
    expect(wrapper.find('[data-testid="shutter-label"]').text()).toBe('Start focus stack')
  })

  it('Single captures once with the chosen options and toasts a failure', async () => {
    const { pinia } = setup()
    const capture = useCaptureStore()
    capture.capture = vi.fn().mockRejectedValue(new Error('Camera refused'))
    await shutter().trigger('click')
    await flushPromises()
    expect(capture.capture).toHaveBeenCalledWith({
      download: true,
      delete_from_camera: false,
      filename_prefix: null,
    })
    expect(useToastsStore(pinia).items.at(-1).message).toBe('Camera refused')
  })

  it('shows the settings of the selected mode under the shutter', async () => {
    setup()
    expect(wrapper.find('.msettings').exists()).toBe(false)
    await button(wrapper, 'Bracket').trigger('click')
    expect(wrapper.find('[data-testid="ev-scale"]').exists()).toBe(true)
    await button(wrapper, 'Bulb').trigger('click')
    expect(wrapper.text()).toContain('Exposure time')
    await button(wrapper, 'Stack').trigger('click')
    expect(wrapper.text()).toContain('Focus step')
  })

  it('disables the shutter with a visible reason when disconnected, busy or without a target', async () => {
    setup({ connected: false })
    expect(shutter().attributes('aria-disabled')).toBe('true')
    expect(wrapper.find('[data-testid="shutter-reason"]').text()).toContain('Connect the camera')
    wrapper.unmount()
    setup({ leasedBy: 'recording' })
    expect(wrapper.find('[data-testid="shutter-reason"]').text()).toBe('Busy: Recording.')
    wrapper.unmount()
    setup()
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = null
    await flushPromises()
    expect(shutter().attributes('aria-disabled')).toBe('true')
    expect(wrapper.find('[data-testid="shutter-reason"]').text()).toContain('No storage target')
  })

  it('shows the Space hint, and hides it when keyboard hints are off', async () => {
    setup()
    expect(wrapper.find('.kbdonly').text()).toBe('Space')
    wrapper.unmount()
    localStorage.setItem('hints', '0')
    const { useKeyboardHints } = await import('@/composables/useKeyboardHints')
    useKeyboardHints().setHints(false)
    setup()
    expect(wrapper.find('.kbdonly').exists()).toBe(false)
    useKeyboardHints().setHints(true)
  })

  it('the shutter becomes a stop button while a bulb exposure runs, and the mode is locked', async () => {
    setup({ leasedBy: 'bulb' })
    useBulbStore().status = { active: true, job_id: 'j1' }
    useShootStore().mode = 'bulb'
    await flushPromises()
    expect(wrapper.find('.shutter.stop').exists()).toBe(true)
    expect(shutter().attributes('aria-label')).toBe('Close shutter')
    expect(shutter().attributes('disabled')).toBeUndefined()
    expect(button(wrapper, 'Single').attributes('disabled')).toBeDefined()
  })

  it('shows the last capture, or says there is none', async () => {
    setup()
    expect(wrapper.find('[data-testid="last-capture"]').exists()).toBe(false)
    useCaptureStore().lastCapture = {
      files: [
        { name: 'DSC_0001.JPG', kind: 'image', path: 'a/DSC_0001.JPG' },
        { name: 'DSC_0001.NEF', kind: 'raw', path: 'a/DSC_0001.NEF' },
      ],
    }
    await flushPromises()
    const t = wrapper.find('[data-testid="last-capture"]').text()
    expect(t).toContain('DSC_0001.JPG')
    expect(t).toContain('JPEG + RAW')
  })
})
