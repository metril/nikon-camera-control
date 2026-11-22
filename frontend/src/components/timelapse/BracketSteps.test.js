import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import BracketSteps from './BracketSteps.vue'
import { draft, resetDraft } from './useDraft'
import { newStep, newRow } from './bracketUtils'

const mk = () =>
  mount(BracketSteps, { global: { plugins: [createTestingPinia({ createSpy: vi.fn })] } })
const step = (label) => newStep([newRow('iso', '100')], label)

describe('BracketSteps', () => {
  beforeEach(() => resetDraft())

  it('removing a step keeps the right rows expanded', async () => {
    draft.bracket.steps = [step('A'), step('B'), step('C')]
    const w = mk()
    await w.findAll('[data-test="step"]')[2].find('button[aria-expanded]').trigger('click') // expand C
    expect(w.findAll('[data-test="step-detail"]')).toHaveLength(1)
    await w.findAll('[aria-label="Remove step"]')[0].trigger('click') // remove A
    const rows = w.findAll('[data-test="step"]')
    expect(rows).toHaveLength(2)
    expect(rows[1].text()).toContain('C')
    expect(rows[1].find('[data-test="step-detail"]').exists()).toBe(true)
    expect(rows[0].find('[data-test="step-detail"]').exists()).toBe(false)
  })

  it('enforces 2 to 15 steps and reorders', async () => {
    draft.bracket.steps = [step('A'), step('B')]
    const w = mk()
    expect(
      w.findAll('[aria-label="Remove step"]').every((b) => b.attributes('disabled') !== undefined),
    ).toBe(true)
    await w.findAll('[aria-label="Move step down"]')[0].trigger('click')
    expect(draft.bracket.steps.map((s) => s.label)).toEqual(['B', 'A'])
    for (let i = 0; i < 20; i++)
      draft.bracket.steps.length < 15 &&
        (await w
          .find('button:not([aria-label])')
          .trigger('click')
          .catch(() => {}))
    draft.bracket.steps = Array.from({ length: 15 }, (_, i) => step(String(i)))
    await w.vm.$nextTick()
    expect(
      w
        .findAll('button')
        .find((b) => b.text() === 'Add step')
        .attributes('disabled'),
    ).toBeDefined()
  })
})
