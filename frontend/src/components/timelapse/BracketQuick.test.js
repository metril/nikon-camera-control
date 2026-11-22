import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { vi } from 'vitest'
import BracketQuick from './BracketQuick.vue'
import { draft, resetDraft } from './useDraft'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'

function setup(connected = false) {
  const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: true })
  const cam = useCameraStore()
  cam.connected = connected
  const settings = useSettingsStore()
  settings.common = [
    { name: 'shutterspeed', choices: ['30', '1/250', 'Bulb', '1/4000'], writable: true },
    { name: 'iso', choices: ['400', '100'], writable: true },
    { name: 'f-number', alias: 'aperture', choices: ['8', '2.8'], writable: true },
    { name: 'exposurecompensation', choices: ['1', '-1', '0'], writable: true },
  ]
  return mount(BracketQuick, { global: { plugins: [pinia] } })
}

describe('BracketQuick', () => {
  beforeEach(() => resetDraft())

  it('uses the camera choices, sorted, and marks fallbacks as not validated', () => {
    const w = setup(true)
    const labels = w
      .find('[data-type="shutter"]')
      .findAll('button')
      .map((b) => b.text())
    expect(labels).toEqual(['1/4000', '1/250', '30', 'Bulb'])
    expect(w.text()).not.toContain('not validated')
    const off = setup(false)
    expect(off.findAll('legend').every((l) => l.text().includes('not validated'))).toBe(true)
  })

  it('one generic toggle works for all four types and keeps order', async () => {
    const w = setup(true)
    for (const [type, pick] of [
      ['exposure', ['1', '-1']],
      ['iso', ['400', '100']],
      ['aperture', ['8', '2.8']],
      ['shutter', ['30', '1/250']],
    ]) {
      for (const label of pick)
        await w
          .find(`[data-type="${type}"]`)
          .findAll('button')
          .find((b) => b.text() === label)
          .trigger('click')
    }
    expect(draft.bracket.quick.exposure).toEqual(['-1', '1'])
    expect(draft.bracket.quick.iso).toEqual(['100', '400'])
    expect(draft.bracket.quick.aperture).toEqual(['2.8', '8'])
    expect(draft.bracket.quick.shutter).toEqual(['1/250', '30'])
    await w
      .find('[data-type="iso"]')
      .findAll('button')
      .find((b) => b.text() === '100')
      .trigger('click')
    expect(draft.bracket.quick.iso).toEqual(['400'])
    expect(w.find('[data-test="quick-shots"]').text()).toBe('7')
  })
})
