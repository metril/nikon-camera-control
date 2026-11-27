import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import CopyToDialog from './CopyToDialog.vue'
import { useStorageStore } from '@/stores/storage'

let w
afterEach(() => w?.unmount())
function setup(locations, props = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const st = useStorageStore(pinia)
  st.targetId = 'a'
  st.locations = locations
  w = mount(CopyToDialog, {
    props: { open: true, count: 2, ...props },
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
}
const loc = (id, mounted = true) => ({ id, name: id, label: id.toUpperCase(), mounted })
const confirm = () => document.body.querySelector('[data-testid=copy-confirm]')

describe('CopyToDialog', () => {
  it('lists other mounted storages only and needs a choice when there are several', async () => {
    setup([loc('a'), loc('b'), loc('c'), loc('d', false)])
    const radios = [...document.body.querySelectorAll('[role=radio]')].map((r) =>
      r.textContent.trim(),
    )
    expect(radios).toEqual(['B', 'C'])
    expect(confirm().disabled).toBe(true)
    document.body.querySelectorAll('[role=radio]')[1].click()
    await w.vm.$nextTick()
    expect(confirm().disabled).toBe(false)
    confirm().click()
    expect(w.emitted('confirm')).toEqual([['c']])
  })

  it('preselects a lone destination', () => {
    setup([loc('a'), loc('b')])
    expect(confirm().disabled).toBe(false)
    expect(document.body.textContent).toContain('Copy 2 files')
  })

  it('explains when there is nowhere to copy to', () => {
    setup([loc('a')])
    expect(document.body.querySelector('[data-testid=copy-none]')).toBeTruthy()
    expect(confirm().disabled).toBe(true)
  })
})
