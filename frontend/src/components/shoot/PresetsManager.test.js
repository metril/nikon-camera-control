import { describe, it, expect, vi, afterEach } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import PresetsManager from './PresetsManager.vue'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'
import { useShootStore } from '@/stores/shoot'
import { downloadBlob } from '@/api'
import { mountCard, bodyButton } from './testing'

vi.mock('@/api', () => ({ api: {}, downloadBlob: vi.fn(), isNoTarget: () => false }))

const night = {
  id: 'night',
  kind: 'settings',
  name: 'Night',
  description: 'High ISO',
  values: { iso: 3200, 'f-number': 'f/1.8' },
}
const bracket = { id: 'builtin-exposure_3', kind: 'bracket', name: '3 shots', builtin: true }

let wrapper
function setup(opts = {}, props = { manageOpen: true }) {
  const r = mountCard(PresetsManager, {
    ...opts,
    props,
    attachTo: document.body,
    setup: () => {
      const p = usePresetsStore()
      p.items = [night, bracket]
      p.fetch = vi.fn().mockResolvedValue()
      const s = useSettingsStore()
      s.common = [
        { name: 'iso', label: 'ISO', value: 3200, writable: true, readonly: false },
        { name: 'batterylevel', label: 'Battery', value: '80%', writable: false, readonly: true },
      ]
      s.fetchCommon = vi.fn().mockResolvedValue()
    },
  })
  wrapper = r.wrapper
  return r
}
const body = () => document.body.textContent
afterEach(() => {
  wrapper?.unmount()
  document.body.innerHTML = ''
})

describe('PresetsManager', () => {
  it('lists settings presets with counts and bracket presets read-only with a Time-lapse link', async () => {
    const { wrapper } = setup()
    await flushPromises()
    const list = document.body.querySelector('[data-testid=settings-presets]')
    expect(list.textContent).toContain('2 settings')
    expect(list.textContent).not.toContain('3 shots')
    expect(document.body.querySelector('[data-testid=bracket-presets]').textContent).toContain(
      '3 shots',
    )
    bodyButton('Edit bracket presets').click()
    expect(wrapper.emitted('navigate')[0]).toEqual(['timelapse'])
  })

  it('apply success lists applied values and remembers the preset name', async () => {
    setup()
    usePresetsStore().apply = vi.fn().mockResolvedValue({ applied: [{ name: 'iso', value: 3200 }] })
    bodyButton('Apply').click()
    await flushPromises()
    expect(document.body.querySelector('[data-testid=result-night]').textContent).toContain(
      'ISO: 3200',
    )
    expect(useShootStore().appliedPreset).toBe('Night')
  })

  it('apply failure says nothing was applied and lists the invalid setting', async () => {
    setup()
    const err = Object.assign(new Error('Invalid value for f-number'), {
      details: { name: 'f-number', value: 'f/1.8', nearby: ['f/2', 'f/2.8'] },
    })
    usePresetsStore().apply = vi.fn().mockRejectedValue(err)
    bodyButton('Apply').click()
    await flushPromises()
    const r = document.body.querySelector('[data-testid=result-night]').textContent
    expect(r).toContain('Nothing was applied')
    expect(r).toContain('Aperture')
    expect(r).toContain('f/2, f/2.8')
  })

  it('save sends the chosen names (writable settings only)', async () => {
    setup({}, { manageOpen: false, saveOpen: true })
    const presets = usePresetsStore()
    presets.fromCamera = vi.fn().mockResolvedValue({ name: 'Mine' })
    await flushPromises()
    expect(body()).not.toContain('Battery')
    const name = document.body.querySelector('input[type=text]')
    name.value = 'Mine'
    name.dispatchEvent(new Event('input'))
    await flushPromises()
    bodyButton('Save preset').click()
    await flushPromises()
    expect(presets.fromCamera).toHaveBeenCalledWith({
      name: 'Mine',
      description: '',
      names: ['iso'],
    })
    expect(useShootStore().appliedPreset).toBe('Mine')
  })

  it('delete needs a confirm click', async () => {
    setup()
    const presets = usePresetsStore()
    presets.remove = vi.fn().mockResolvedValue()
    bodyButton('Delete').click()
    await flushPromises()
    expect(presets.remove).not.toHaveBeenCalled()
    bodyButton('Confirm?').click()
    await flushPromises()
    expect(presets.remove).toHaveBeenCalledWith('night')
  })

  it('export downloads the JSON', async () => {
    setup()
    usePresetsStore().exportAll = vi.fn().mockResolvedValue({ schema_version: 1, presets: [night] })
    bodyButton('Export').click()
    await flushPromises()
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), 'presets.json')
  })

  it('import sends the file with the replace toggle and renders the per-item results', async () => {
    setup()
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
    const input = document.body.querySelector('[data-testid=import-file]')
    const doc = { schema_version: 1, presets: [{ name: 'A' }] }
    Object.defineProperty(input, 'files', {
      value: [{ text: async () => JSON.stringify(doc) }],
    })
    input.dispatchEvent(new Event('change'))
    await flushPromises()
    const call = presets.importPresets.mock.calls[0][0]
    expect(call.presets).toEqual(doc.presets)
    expect(typeof call.replace).toBe('boolean')
    const r = document.body.querySelector('[data-testid=import-result]').textContent
    expect(r).toContain('1 created, 1 skipped, 1 failed')
    expect(r).toContain('bad value')
    expect(r).toContain('Skipped')
  })

  it('applying is disabled with a visible reason when disconnected or busy', async () => {
    setup({ connected: false })
    expect(document.body.querySelector('[data-testid=presets-reason]').textContent).toContain(
      'Camera not connected',
    )
    expect(bodyButton('Apply').disabled).toBe(true)
    wrapper.unmount()
    document.body.innerHTML = ''
    setup({ leasedBy: 'recording' })
    expect(document.body.querySelector('[data-testid=presets-reason]').textContent).toContain(
      'Busy: Recording',
    )
    expect(bodyButton('Apply').disabled).toBe(true)
  })
})
