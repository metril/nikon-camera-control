import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import SettingsPanel from './SettingsPanel.vue'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'
import { useToastsStore } from '@/stores/toasts'
import { api } from '@/api'
import { useLayoutMode, resetLayoutMode } from '@/composables/useLayoutMode'

vi.mock('@/api', async (importOriginal) => {
  const orig = await importOriginal()
  return {
    ...orig,
    api: { ...orig.api, setSetting: vi.fn(), listSettings: vi.fn(), refreshSettings: vi.fn() },
  }
})

const S = (name, type, value, extra = {}) => ({
  name,
  label: name.toUpperCase(),
  path: `/main/${name}`,
  type,
  value,
  readonly: false,
  writable: true,
  choices: [],
  range: null,
  alias: null,
  ...extra,
})
const COMMON = [
  S('iso', 'menu', '100', { choices: ['100', '200', '400', '800', '1600', '3200'] }),
  S('whitebalance', 'radio', 'Auto', { choices: ['Auto', 'Sunny'] }),
  S('exposurecompensation', 'range', 0, { range: { min: -5, max: 5, step: 0.5 } }),
  S('batterylevel', 'text', '80%', { readonly: true, writable: false }),
]

function setup({ connected = true, leasedBy = null } = {}) {
  vi.clearAllMocks()
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const camera = useCameraStore()
  camera.connected = connected
  camera.leasedBy = leasedBy
  const settings = useSettingsStore()
  settings.common = JSON.parse(JSON.stringify(COMMON))
  api.listSettings.mockResolvedValue([])
  return { pinia, settings }
}
const mnt = (pinia) => mount(SettingsPanel, { global: { plugins: [pinia] } })

describe('SettingsPanel', () => {
  it('renders fields by widget type in groups', () => {
    const { pinia } = setup()
    const w = mnt(pinia)
    expect(w.text()).toContain('Exposure')
    expect(w.text()).toContain('Image')
    expect(w.text()).toContain('Other')
    expect(w.find('[data-setting="whitebalance"] button[aria-pressed]').exists()).toBe(true) // segmented
    expect(w.find('[data-setting="iso"] select').exists()).toBe(true)
    expect(w.find('[data-setting="batterylevel"] [data-testid="readonly-value"]').text()).toBe(
      '80%',
    )
  })

  it('Show all focuses the search on desktop but not on touch (no phone keyboard pop-up)', async () => {
    for (const [pref, focused] of [
      ['desktop', true],
      ['touch', false],
    ]) {
      resetLayoutMode()
      useLayoutMode().setPref(pref)
      const { pinia } = setup()
      const w = mount(SettingsPanel, { global: { plugins: [pinia] }, attachTo: document.body })
      await w.find('[aria-expanded]').trigger('click')
      await flushPromises()
      const input = w.find('[data-testid="all-settings"] input').element
      expect(document.activeElement === input, pref).toBe(focused)
      w.unmount()
    }
    resetLayoutMode()
  })

  it('shows an empty state when disconnected', () => {
    const { pinia } = setup({ connected: false })
    const w = mnt(pinia)
    expect(w.text()).toContain('Connect the camera to change settings')
    expect(w.find('[data-setting]').exists()).toBe(false)
  })

  it('locks fields with the reason when leased', () => {
    const { pinia } = setup({ leasedBy: 'timelapse' })
    const w = mnt(pinia)
    expect(w.text()).toContain('Busy: Time-lapse')
    expect(w.find('[data-setting="iso"] select').attributes('disabled')).toBeDefined()
  })

  it('calls settings.set and keeps other fields enabled during the write', async () => {
    const { pinia, settings } = setup()
    const releases = []
    const spy = vi
      .spyOn(settings, 'set')
      .mockImplementation(() => new Promise((r) => releases.push(r)))
    const w = mnt(pinia)
    await w.find('[data-setting="whitebalance"] button:last-of-type').trigger('click')
    expect(spy).toHaveBeenCalledWith('whitebalance', 'Sunny')
    await w.vm.$nextTick()
    expect(w.find('[data-setting="whitebalance"] [data-testid="saving"]').exists()).toBe(true)
    expect(w.find('[data-setting="iso"] select').attributes('disabled')).toBeUndefined()
    expect(w.find('[data-setting="whitebalance"] button').attributes('disabled')).toBeUndefined()
    await w.find('[data-setting="iso"] select').setValue('400')
    expect(spy).toHaveBeenCalledWith('iso', '400')
    releases.forEach((r) => r())
    await flushPromises()
    expect(w.find('[data-testid="saving"]').exists()).toBe(false)
  })

  it('shows the error inline and as a toast when the write rolls back', async () => {
    const { pinia, settings } = setup()
    api.setSetting.mockRejectedValue(new Error('Camera refused'))
    const w = mnt(pinia)
    await w.find('[data-setting="iso"] select').setValue('400')
    await flushPromises()
    expect(settings.get('iso')).toBe('100') // store rolled back
    expect(w.find('[data-setting="iso"] [role="alert"]').text()).toBe('Camera refused')
    expect(useToastsStore().items.at(-1).kind).toBe('error')
  })

  it('show all loads the tree, search filters, non-writable are disabled with a tooltip', async () => {
    const { pinia } = setup()
    api.listSettings.mockResolvedValue([
      S('colorspace', 'radio', 'sRGB', { choices: ['sRGB', 'Adobe'] }),
      S('serialnumber', 'text', '123', { readonly: true, writable: false }),
    ])
    const w = mnt(pinia)
    await w.find('[data-testid="show-all"]').trigger('click')
    await flushPromises()
    expect(api.listSettings).toHaveBeenCalledWith({ query: { group: 'all' } })
    const box = w.find('[data-testid="all-settings"]')
    expect(box.findAll('[data-setting]')).toHaveLength(2)
    expect(box.find('[data-setting="serialnumber"]').attributes('title')).toBe(
      'Read-only on the camera',
    )
    await box.find('input').setValue('serial')
    expect(box.findAll('[data-setting]')).toHaveLength(1)
  })

  it('Refresh calls refresh_settings', async () => {
    const { pinia } = setup()
    api.refreshSettings.mockResolvedValue({})
    const w = mnt(pinia)
    await w.find('[data-testid="refresh"]').trigger('click')
    await flushPromises()
    expect(api.refreshSettings).toHaveBeenCalledTimes(1)
  })
})
