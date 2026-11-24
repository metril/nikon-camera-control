import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import ModeWarning from './ModeWarning.vue'
import { useCameraStore } from '@/stores/camera'
import { useSettingsStore } from '@/stores/settings'

function setup(connected, mode) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  useCameraStore().connected = connected
  if (mode !== undefined)
    useSettingsStore().common = [{ name: 'expprogram', type: 'radio', value: mode }]
  return mount(ModeWarning, { global: { plugins: [pinia] } })
}

describe('ModeWarning', () => {
  beforeEach(() => localStorage.clear())

  it('is hidden when disconnected', () => {
    expect(setup(false, 'AUTO').find('[data-testid="mode-warning"]').exists()).toBe(false)
  })
  it('stays quiet while the mode is unknown', () => {
    expect(setup(true).find('[data-testid="mode-warning"]').exists()).toBe(false)
  })
  it('shows the current mode when it is not P/A/S/M', () => {
    const w = setup(true, 'AUTO')
    expect(w.find('[data-testid="current-mode"]').text()).toBe('AUTO')
  })
  it('is hidden for a usable mode', () => {
    expect(setup(true, 'M').find('[data-testid="mode-warning"]').exists()).toBe(false)
    expect(setup(true, 'Aperture Priority').find('[data-testid="mode-warning"]').exists()).toBe(
      false,
    )
  })
  it('stays dismissed after a reload', async () => {
    const w = setup(true, 'AUTO')
    await w.find('button[aria-label="Dismiss"]').trigger('click')
    expect(w.find('[data-testid="mode-warning"]').exists()).toBe(false)
    expect(setup(true, 'AUTO').find('[data-testid="mode-warning"]').exists()).toBe(false)
  })
})
