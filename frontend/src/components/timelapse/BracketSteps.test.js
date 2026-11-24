import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import BracketSteps from './BracketSteps.vue'
import { draft, resetDraft } from './useDraft'
import { newStep, newRow } from './bracketUtils'

const mk = (props = {}) =>
  mount(BracketSteps, { props, global: { plugins: [createTestingPinia({ createSpy: vi.fn })] } })
const step = (label) => newStep([newRow('iso', '100')], label)
const btn = (w, text) => w.findAll('button').find((b) => b.text().includes(text))

describe('BracketSteps', () => {
  beforeEach(() => resetDraft())

  it('shows every step expanded with label, delay in seconds and setting rows', () => {
    draft.bracket.steps = [step('A'), newStep([newRow('iso', '100')], 'B', 1500)]
    const w = mk()
    const cards = w.findAll('[data-test="step"]')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('Step 1')
    expect(cards[0].findAll('[data-test="setting-row"]')).toHaveLength(1)
    expect(cards[1].findAll('input')[1].element.value).toBe('1.5')
  })

  it('removing a step removes exactly that card', async () => {
    draft.bracket.steps = [step('A'), step('B'), step('C')]
    const w = mk()
    await w.find('[aria-label="Remove step 1"]').trigger('click')
    expect(draft.bracket.steps.map((s) => s.label)).toEqual(['B', 'C'])
    expect(w.findAll('[data-test="step"]')).toHaveLength(2)
  })

  it('writes the delay back in milliseconds', async () => {
    draft.bracket.steps = [step('A'), step('B')]
    const w = mk()
    const delay = w.findAll('[data-test="step"]')[0].findAll('input')[1]
    await delay.setValue('2.5')
    await delay.trigger('change')
    expect(draft.bracket.steps[0].delay_ms).toBe(2500)
  })

  it('enforces 2 to 15 steps and reorders', async () => {
    draft.bracket.steps = [step('A'), step('B')]
    const w = mk()
    expect(
      [1, 2].every(
        (n) => w.find(`[aria-label="Remove step ${n}"]`).attributes('disabled') !== undefined,
      ),
    ).toBe(true)
    await w.find('[aria-label="Move step 1 down"]').trigger('click')
    expect(draft.bracket.steps.map((s) => s.label)).toEqual(['B', 'A'])
    for (let i = 0; i < 20; i++) await btn(w, 'Add step').trigger('click')
    expect(draft.bracket.steps).toHaveLength(15)
    expect(btn(w, 'Add step').attributes('disabled')).toBeDefined()
  })

  it('adds and removes setting rows, keeping at least one', async () => {
    draft.bracket.steps = [step('A'), step('B')]
    const w = mk()
    const card = () => w.findAll('[data-test="step"]')[0]
    expect(card().find('[aria-label="Remove setting"]').attributes('disabled')).toBeDefined()
    await btn(card(), 'Add setting').trigger('click')
    expect(card().findAll('[data-test="setting-row"]')).toHaveLength(2)
    await card().find('[aria-label="Remove setting"]').trigger('click')
    expect(card().findAll('[data-test="setting-row"]')).toHaveLength(1)
  })

  it('locks every control while disabled', () => {
    draft.bracket.steps = [step('A'), step('B')]
    const w = mk({ disabled: true })
    expect(w.findAll('button').every((b) => b.attributes('disabled') !== undefined)).toBe(true)
  })
})
