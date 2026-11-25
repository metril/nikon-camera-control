import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import ExposureStrip from './ExposureStrip.vue'
import { useCameraStore } from '@/stores/camera'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'
import { useShootStore } from '@/stores/shoot'
import { mountCard } from './testing'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {}, downloadBlob: vi.fn() }))

const S = (name, value, choices = [], extra = {}) => ({
  name,
  label: name,
  type: 'menu',
  value,
  choices,
  writable: true,
  readonly: false,
  range: null,
  ...extra,
})
const settings = (mode = 'A') => [
  S('expprogram', mode, ['P', 'A', 'S', 'M'], { readonly: true, writable: false }),
  S('shutterspeed', '1/250', ['1/125', '1/250', '1/500']),
  S('f-number', '5.6', ['4', '5.6', '8']),
  S('iso', '400', ['200', '400', '800']),
  S('exposurecompensation', '0.3', ['-0.3', '0', '0.3', '0.7']),
  S('whitebalance', 'Auto', ['Auto', 'Daylight']),
]

let wrapper
function setup({ mode = 'A', ...opts } = {}) {
  const r = mountCard(ExposureStrip, {
    ...opts,
    attachTo: document.body,
    setup: () => {
      const st = useSettingsStore()
      st.common = settings(mode)
      st.fetchCommon = vi.fn().mockResolvedValue()
      st.set = vi.fn().mockResolvedValue({})
      const p = usePresetsStore()
      p.items = [
        {
          id: 'studio',
          kind: 'settings',
          name: 'Studio',
          description: 'M · 1/125',
          values: { iso: 100 },
        },
        { id: 'br', kind: 'bracket', name: '3 shots' },
      ]
      p.fetch = vi.fn().mockResolvedValue()
      useCameraStore().storage = { cards: [{ free_images: 1284, free_kb: 100 }] }
    },
  })
  wrapper = r.wrapper
  return r
}
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ''
})
const cell = (k) => wrapper.find(`[data-k="${k}"]`)
const picker = () => document.body.querySelector('[data-test="picker"]')
const options = () => [...document.body.querySelectorAll('[role="option"]')]

describe('ExposureStrip', () => {
  it('shows unknown shots left as a dash, not 0', async () => {
    setup()
    useCameraStore().storage = { cards: [{ free_images: null, free_kb: 100 }] }
    await wrapper.vm.$nextTick()
    expect(cell('shots').text()).toContain('–')
    expect(cell('shots').text()).not.toContain('0')
  })

  it('shows mode, shutter, aperture, ISO, EV, WB, shots left and preset with short labels', () => {
    setup()
    const labels = wrapper.findAll('.cell .k').map((n) => n.text())
    expect(labels).toEqual([
      'Mode',
      'Shutter',
      'Aperture',
      'ISO',
      'EV',
      'WB',
      'Shots left',
      'Preset',
    ])
    expect(cell('aperture').text()).toContain('f/5.6')
    expect(cell('iso').text()).toContain('400')
    expect(cell('comp').text()).toContain('+0.3')
    expect(cell('shots').text()).toContain('1,284')
    expect(cell('preset').text()).toContain('None')
    // full names for assistive tech and tooltips
    expect(cell('comp').attributes('aria-label')).toBe('Exposure compensation: +0.3')
    expect(cell('comp').attributes('title')).toBe('Exposure compensation')
    expect(cell('wb').attributes('aria-label')).toBe('White balance: Auto')
  })

  it('mutes values the mode sets by itself and tags them AUTO', () => {
    setup({ mode: 'A' })
    expect(cell('shutter').find('.v').classes()).toContain('autov')
    expect(cell('shutter').find('.auto').text()).toBe('AUTO')
    expect(cell('shutter').element.tagName).toBe('DIV') // not editable
    expect(cell('aperture').find('.auto').exists()).toBe(false)
    expect(cell('aperture').element.tagName).toBe('BUTTON')
  })

  it('shows Meter instead of EV in manual mode', async () => {
    setup({ mode: 'M' })
    useSettingsStore().common.push(S('lightmeter', '0.3', [], { readonly: true, writable: false }))
    await flushPromises()
    expect(wrapper.find('[data-k="comp"]').exists()).toBe(false)
    expect(cell('meter').text()).toContain('Meter')
    expect(cell('shutter').find('.auto').exists()).toBe(false)
  })

  it('hides the Meter cell in manual mode when the camera reports no reading', () => {
    setup({ mode: 'M' })
    expect(wrapper.find('[data-k="meter"]').exists()).toBe(false)
    expect(wrapper.findAll('.cell')).toHaveLength(7)
  })

  it('opens a picker with the camera values; choosing one writes the setting', async () => {
    setup()
    await cell('iso').trigger('click')
    expect(cell('iso').attributes('aria-expanded')).toBe('true')
    expect(options().map((o) => o.textContent.trim())).toEqual(['200', '400', '800'])
    expect(options()[1].getAttribute('aria-selected')).toBe('true')
    options()[2].click()
    await flushPromises()
    expect(useSettingsStore().set).toHaveBeenCalledWith('iso', '800')
    expect(picker()).toBeNull()
  })

  it('Esc closes the picker and returns focus to the value', async () => {
    setup()
    await cell('iso').trigger('click')
    picker().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(picker()).toBeNull()
    expect(document.activeElement).toBe(cell('iso').element)
  })

  it('[ and ] step the focused value', async () => {
    setup()
    cell('iso').element.focus()
    await cell('iso').trigger('keydown', { key: ']' })
    expect(useSettingsStore().set).toHaveBeenCalledWith('iso', '800')
    await cell('iso').trigger('keydown', { key: '[' })
    expect(useSettingsStore().set).toHaveBeenLastCalledWith('iso', '200')
  })

  it('A, S, I and E can focus the values (focusCell)', () => {
    setup()
    wrapper.vm.focusCell('aperture')
    expect(document.activeElement).toBe(cell('aperture').element)
    wrapper.vm.focusCell('comp')
    expect(document.activeElement).toBe(cell('comp').element)
  })

  it('the preset picker lists settings presets with descriptions and applies one', async () => {
    setup()
    const presets = usePresetsStore()
    presets.apply = vi.fn().mockResolvedValue({ applied: [] })
    await cell('preset').trigger('click')
    expect(picker().classList.contains('wide')).toBe(true)
    expect(options().map((o) => o.querySelector('.lbl').textContent)).toEqual(['None', 'Studio'])
    expect(options().map((o) => o.querySelector('.sub').textContent)).toEqual([
      'Keep the current settings',
      'M · 1/125',
    ])
    expect(picker().textContent).toContain('Save current settings as preset')
    expect(picker().textContent).toContain('Manage presets')
    options()[1].click()
    await flushPromises()
    expect(presets.apply).toHaveBeenCalledWith('studio')
    expect(useShootStore().appliedPreset).toBe('Studio')
    expect(cell('preset').text()).toContain('Studio')
  })

  it('editing a value by hand clears the applied preset', async () => {
    setup()
    useShootStore().appliedPreset = 'Studio'
    await cell('iso').trigger('click')
    options()[0].click()
    await flushPromises()
    expect(useShootStore().appliedPreset).toBeNull()
  })

  it('shows dashes and offers no pickers while disconnected', () => {
    setup({ connected: false })
    expect(wrapper.findAll('button.cell')).toHaveLength(0)
    expect(cell('iso').text()).toContain('–')
  })

  it('locks editing with a reason while another feature holds the camera', () => {
    setup({ leasedBy: 'timelapse' })
    expect(cell('iso').element.tagName).toBe('DIV')
    expect(cell('iso').attributes('title')).toContain('Busy: Time-lapse')
  })
})
