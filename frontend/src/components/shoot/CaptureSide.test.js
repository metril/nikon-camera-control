import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import CaptureSide from './CaptureSide.vue'
import { useBulbStore } from '@/stores/bulb'
import { useCaptureStore } from '@/stores/capture'
import { useShootStore } from '@/stores/shoot'
import { useStorageStore } from '@/stores/storage'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import { resetLayoutMode, useLayoutMode } from '@/composables/useLayoutMode'
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

  it('shows where photos go, and Single only triggers when downloads are off', async () => {
    const { pinia } = setup()
    useStorageStore().locations = [{ id: 'a', name: 'Studio SSD', mounted: true }]
    useStorageStore().targetId = 'a'
    useConfigStore().config = { camera: { download_photos: true } }
    await flushPromises()
    expect(wrapper.find('[data-testid="download-chip"]').text()).toBe('Downloads to Studio SSD')
    const capture = useCaptureStore()
    capture.trigger = vi.fn().mockResolvedValue({ ok: true })
    capture.capture = vi.fn()
    useConfigStore().config = { camera: { download_photos: false } }
    await flushPromises()
    expect(wrapper.find('[data-testid="download-chip"]').text()).toBe(
      'Trigger only · stays on card',
    )
    await shutter().trigger('click')
    await flushPromises()
    expect(capture.trigger).toHaveBeenCalledTimes(1)
    expect(capture.capture).not.toHaveBeenCalled()
    expect(useToastsStore(pinia).items.at(-1).message).toBe(
      'Shutter fired · Photo stays on the card',
    )
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
    expect(wrapper.find('[data-testid="shutter-reason"]').text()).toContain('No storage chosen')
  })

  it('trigger-only Single stays enabled without storage chosen', async () => {
    setup()
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = null
    useConfigStore().config = { camera: { download_photos: false } }
    await flushPromises()
    expect(shutter().attributes('aria-disabled')).not.toBe('true')
    useConfigStore().config = { camera: { download_photos: true } }
    await flushPromises()
    expect(shutter().attributes('aria-disabled')).toBe('true')
  })

  it('shows the Space hint, and hides it when keyboard hints are off', async () => {
    setup()
    expect(wrapper.find('.slabel kbd').text()).toBe('Space')
    wrapper.unmount()
    localStorage.setItem('hints', '0')
    const { useKeyboardHints } = await import('@/composables/useKeyboardHints')
    useKeyboardHints().setHints(false)
    setup()
    expect(wrapper.find('.slabel kbd').exists()).toBe(false)
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

  it('without storage chosen: says photos are not saved, offers card-only and the Storage link', async () => {
    setup()
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = null
    const config = useConfigStore()
    config.config = { camera: { download_photos: true } }
    config.patch = vi.fn().mockResolvedValue({})
    await flushPromises()
    expect(wrapper.find('[data-testid="download-chip"]').text()).toBe('Not saving to storage')
    expect(wrapper.find('[data-test="no-target"] a').attributes('href')).toBe(
      '#/settings?section=storage',
    )
    const click = new MouseEvent('click', { bubbles: true, cancelable: true })
    wrapper.find('[data-test="no-target"] a').element.dispatchEvent(click)
    expect(click.defaultPrevented).toBe(true) // the emit navigates; the href must not add a second entry
    expect(wrapper.emitted('open-settings')[0]).toEqual(['storage'])
    await button(wrapper, 'Shoot to card only').trigger('click')
    expect(config.patch).toHaveBeenCalledWith({ camera: { download_photos: false } })
  })

  it('does not offer card-only for modes that need storage chosen', async () => {
    setup()
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = null
    useConfigStore().config = { camera: { download_photos: true } }
    useShootStore().mode = 'bracket'
    await flushPromises()
    expect(button(wrapper, 'Shoot to card only')).toBeUndefined()
  })

  it('toasts when saving card-only fails', async () => {
    const { pinia } = setup()
    const storage = useStorageStore()
    storage.loaded = true
    storage.targetId = null
    const config = useConfigStore()
    config.config = { camera: { download_photos: true } }
    config.patch = vi.fn().mockRejectedValue(new Error('nope'))
    await flushPromises()
    await button(wrapper, 'Shoot to card only').trigger('click')
    await flushPromises()
    expect(useToastsStore(pinia).items.at(-1).message).toContain('nope')
  })

  describe('touch layout', () => {
    const useTouch = () => {
      localStorage.setItem('layout', 'touch')
      resetLayoutMode()
    }
    afterEach(() => {
      localStorage.removeItem('layout')
      resetLayoutMode()
    })

    it('desktop shows the mode settings inline and no summary line', async () => {
      setup()
      useShootStore().mode = 'bracket'
      await flushPromises()
      expect(wrapper.find('[data-testid="inline-settings"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="mode-summary"]').exists()).toBe(false)
    })

    it.each([
      ['bracket', /^Bracket · 3 frames · 1 EV$/, 'Frames'],
      ['bulb', /^Bulb · 30 s$/, 'Exposure'],
      ['stack', /^Stack · 10 shots$/, 'Settle time'],
    ])('%s: a one-line summary opens its settings in a popover', async (mode, text, label) => {
      useTouch()
      setup()
      useShootStore().mode = mode
      await flushPromises()
      expect(useLayoutMode().isTouch.value).toBe(true)
      expect(wrapper.find('[data-testid="inline-settings"]').exists()).toBe(false)
      const sum = wrapper.find('[data-testid="mode-summary"]')
      expect(sum.text()).toMatch(text)
      expect(document.body.querySelector('[role="dialog"]')).toBeNull()
      await sum.trigger('click')
      await flushPromises()
      const dlg = document.body.querySelector('[data-testid="mode-settings-popover"]')
      expect(dlg).not.toBeNull()
      expect(dlg.textContent).toContain(label) // every control of the mode is reachable
      const done = [...dlg.querySelectorAll('button')].find((b) => b.textContent === 'Done')
      done.click()
      await flushPromises()
      expect(document.body.querySelector('[role="dialog"]')).toBeNull()
    })

    it('Single has a static summary and no popover', async () => {
      useTouch()
      setup()
      await flushPromises()
      const sum = wrapper.find('[data-testid="mode-summary"]')
      expect(sum.text()).toBe('Single shot · no extra settings')
      expect(sum.element.tagName).not.toBe('BUTTON')
    })
  })
})
