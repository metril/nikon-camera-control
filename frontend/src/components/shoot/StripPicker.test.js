import { describe, it, expect, vi, afterEach } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import StripPicker from './StripPicker.vue'

const anchorAt = (top, bottom) => ({
  getBoundingClientRect: () => ({ top, bottom, left: 100 }),
  isConnected: false,
})
const mountAt = (anchor) =>
  mount(StripPicker, {
    props: { title: 'ISO', options: [{ value: 1, label: '100' }], anchor },
    attachTo: document.body,
  })
afterEach(() => (document.body.innerHTML = ''))

describe('StripPicker placement', () => {
  it('opens below with room, flips above when the cell sits near the bottom', async () => {
    window.innerHeight = 768
    mountAt(anchorAt(100, 140))
    await nextTick()
    const p = document.querySelector('.picker')
    expect(p.style.top).toBe('146px')
    expect(p.style.bottom).toBe('')
    document.body.innerHTML = ''
    mountAt(anchorAt(700, 740))
    await nextTick()
    const q = document.querySelector('.picker')
    expect(q.style.bottom).toBe('74px')
    expect(q.style.top).toBe('')
  })
  it('repositions on resize', () => {
    window.innerHeight = 768
    let top = 100
    const anchor = { getBoundingClientRect: () => ({ top, bottom: top + 40, left: 100 }) }
    mountAt(anchor)
    top = 700
    window.dispatchEvent(new Event('resize'))
    return vi.waitFor(() => expect(document.querySelector('.picker').style.bottom).toBe('74px'))
  })
})

describe('StripPicker scroll', () => {
  it('repositions on outside scroll but ignores scrolling its own list', async () => {
    window.innerHeight = 768
    const rect = vi.fn(() => ({ top: 100, bottom: 140, left: 100 }))
    mountAt({ getBoundingClientRect: rect })
    await nextTick()
    rect.mockClear()
    document.querySelector('.picker').dispatchEvent(new Event('scroll'))
    expect(rect).not.toHaveBeenCalled()
    document.body.dispatchEvent(new Event('scroll'))
    expect(rect).toHaveBeenCalled()
  })
})
