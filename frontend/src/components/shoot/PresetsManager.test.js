import { describe, it, expect, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import PresetsCard from './PresetsCard.vue'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'
import { downloadBlob } from '@/api'
import { mountCard, button } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn() }))

const night = {
  id: 'night',
  kind: 'settings',
  name: 'Night',
  description: 'High ISO',
  values: { iso: 3200, 'f-number': 'f/1.8' },
}
const bracket = { id: 'builtin-exposure_3', kind: 'bracket', name: '3 shots', builtin: true }

function setup(opts) {
  return mountCard(PresetsCard, {
    ...opts,
    setup: () => {
      const p = usePresetsStore()
      p.items = [night, bracket]
      p.fetch = vi.fn().mockResolvedValue()
      const s = useSettingsStore()
      s.common = [
        { name: 'iso', label: 'ISO', value: 3200, writable: true, readonly: false },
        { name: 'batterylevel', label: 'Battery', value: '80%', writable: false, readonly: true },
      ]
    },
  })
}

describe('PresetsCard', () => {
  it('lists settings presets with counts and bracket presets read-only with a Time-lapse link', async () => {
    const { wrapper } = setup()
    expect(wrapper.find('[data-testid=settings-presets]').text()).toContain('2 settings')
    expect(wrapper.find('[data-testid=settings-presets]').text()).not.toContain('3 shots')
    expect(wrapper.find('[data-testid=bracket-presets]').text()).toContain('3 shots')
    await button(wrapper, 'Edit bracket presets').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['timelapse'])
  })

  it('apply success lists applied values', async () => {
    const { wrapper } = setup()
    usePresetsStore().apply = vi.fn().mockResolvedValue({ applied: [{ name: 'iso', value: 3200 }] })
    await button(wrapper, 'Apply').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid=result-night]').text()).toContain('iso = 3200')
  })

  it('apply failure says nothing was applied and lists the invalid setting', async () => {
    const { wrapper } = setup()
    const err = Object.assign(new Error('Invalid value for f-number'), {
      details: { name: 'f-number', value: 'f/1.8', nearby: ['f/2', 'f/2.8'] },
    })
    usePresetsStore().apply = vi.fn().mockRejectedValue(err)
    await button(wrapper, 'Apply').trigger('click')
    await flushPromises()
    const r = wrapper.find('[data-testid=result-night]')
    expect(r.text()).toContain('Nothing was applied')
    expect(r.text()).toContain('f-number')
    expect(r.text()).toContain('f/2, f/2.8')
  })

  it('save-from-camera sends the chosen names (writable settings only)', async () => {
    const { wrapper } = setup()
    const presets = usePresetsStore()
    presets.fromCamera = vi.fn().mockResolvedValue({})
    await button(wrapper, 'Save current settings as preset').trigger('click')
    await flushPromises()
    expect(document.body.textContent).not.toContain('Battery')
    const name = document.body.querySelector('input[type=text]')
    name.value = 'Mine'
    name.dispatchEvent(new Event('input'))
    await flushPromises()
    ;[...document.body.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Save preset'))
      .click()
    await flushPromises()
    expect(presets.fromCamera).toHaveBeenCalledWith({
      name: 'Mine',
      description: '',
      names: ['iso'],
    })
  })

  it('delete needs a confirm click', async () => {
    const { wrapper } = setup()
    const presets = usePresetsStore()
    presets.remove = vi.fn().mockResolvedValue()
    await button(wrapper, 'Delete').trigger('click')
    expect(presets.remove).not.toHaveBeenCalled()
    await button(wrapper, 'Confirm?').trigger('click')
    expect(presets.remove).toHaveBeenCalledWith('night')
  })

  it('export downloads the JSON', async () => {
    const { wrapper } = setup()
    usePresetsStore().exportAll = vi.fn().mockResolvedValue({ schema_version: 1, presets: [night] })
    await button(wrapper, 'Export').trigger('click')
    await flushPromises()
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), 'presets.json')
  })

  it('import sends the file with the replace toggle and renders the per-item results', async () => {
    const { wrapper } = setup()
    const presets = usePresetsStore()
    presets.importPresets = vi.fn().mockResolvedValue({
      created: 1,
      skipped: 1,
      failed: 1,
      items: [
        { index: 0, name: 'A', status: 'created' },
        { index: 1, name: 'B', status: 'skipped' },
        { index: 2, name: 'C', status: 'error', error: 'bad value' },
      ],
    })
    const input = wrapper.find('[data-testid=import-file]')
    const doc = { schema_version: 1, presets: [{ name: 'A' }] }
    Object.defineProperty(input.element, 'files', {
      value: [{ text: async () => JSON.stringify(doc) }],
    })
    await input.trigger('change')
    await flushPromises()
    const call = presets.importPresets.mock.calls[0][0]
    expect(call.presets).toEqual(doc.presets)
    expect(typeof call.replace).toBe('boolean')
    const r = wrapper.find('[data-testid=import-result]')
    expect(r.text()).toContain('1 created, 1 skipped, 1 failed')
    expect(r.text()).toContain('bad value')
    expect(r.text()).toContain('skipped')
  })

  it('disabled states: disconnected and leased', () => {
    expect(setup({ connected: false }).wrapper.text()).toContain('Camera not connected')
    const { wrapper } = setup({ leasedBy: 'recording' })
    expect(button(wrapper, 'Apply').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid=busy]').text()).toBe('Busy: recording')
  })
})
