import { describe, it, expect, vi } from 'vitest'
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
  it('is hidden when disconnected', () => {
    expect(setup(false).find('[data-testid="mode-warning"]').exists()).toBe(false)
  })
  it('shows the reminder when the mode is unknown', () => {
    expect(setup(true).text()).toContain('Mode Dial Requirement')
  })
  it('shows the current mode when it is not P/A/S/M', () => {
    const w = setup(true, 'AUTO')
    expect(w.find('[data-testid="current-mode"]').text()).toContain('AUTO')
  })
  it('is hidden for a usable mode', () => {
    expect(setup(true, 'M').find('[data-testid="mode-warning"]').exists()).toBe(false)
  })
  it('can be dismissed', async () => {
    const w = setup(true)
    await w.find('button[aria-label="Dismiss mode warning"]').trigger('click')
    expect(w.find('[data-testid="mode-warning"]').exists()).toBe(false)
  })
})
