import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { resetLayoutMode } from '@/composables/useLayoutMode'
import SelectionBar from './SelectionBar.vue'

const labels = (w) => w.findAll('button').map((b) => b.text() || b.attributes('aria-label'))
const mountBar = (props = {}) => mount(SelectionBar, { props: { count: 3, ...props } })

describe('SelectionBar', () => {
  beforeEach(() => {
    localStorage.clear()
    resetLayoutMode()
  })

  it('touch: Select all, Copy to…, Delete, Done and no download', () => {
    localStorage.setItem('layout', 'touch')
    resetLayoutMode()
    const w = mountBar()
    expect(labels(w)).toEqual(['Select all', 'Copy to…', 'Delete', 'Done'])
    expect(w.text()).toContain('3 selected')
  })

  it('desktop: Download as ZIP, Copy to… and Delete, with a clear button', async () => {
    localStorage.setItem('layout', 'desktop')
    resetLayoutMode()
    const w = mountBar()
    expect(labels(w)).toEqual([
      'Select all',
      'Download as ZIP',
      'Copy to…',
      'Delete',
      'Clear selection',
    ])
    await w.find('[data-testid=zip]').trigger('click')
    await w.find('[data-testid=copy-to]').trigger('click')
    await w.find('[aria-label="Clear selection"]').trigger('click')
    expect(Object.keys(w.emitted())).toEqual(expect.arrayContaining(['zip', 'copy', 'done']))
  })

  it('Delete asks first; Keep backs out and confirming emits delete', async () => {
    const w = mountBar()
    await w.find('[data-testid=delete]').trigger('click')
    expect(w.emitted('delete')).toBeUndefined()
    await w
      .findAll('button')
      .find((b) => b.text() === 'Keep')
      .trigger('click')
    await w.find('[data-testid=delete]').trigger('click')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Delete 3 items')
      .trigger('click')
    expect(w.emitted('delete')).toHaveLength(1)
  })

  it('disables the actions with nothing selected and shows Clear once all are selected', () => {
    const w = mountBar({ count: 0, allSelected: true })
    expect(w.find('[data-testid=copy-to]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid=delete]').attributes('disabled')).toBeDefined()
    expect(labels(w)[0]).toBe('Clear')
  })

  it('a custom copy label replaces Copy to…', () => {
    expect(labels(mountBar({ copyLabel: 'Save to storage' }))).toContain('Save to storage')
  })
})
