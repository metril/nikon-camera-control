import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// jsdom does no layout, so guard the CSS contract that keeps the kiosk page from scrolling/shifting.
const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

describe('scroll layout', () => {
  it('reserves the root scrollbar gutter so pages do not shift', () => {
    expect(read('./style.css')).toMatch(/html\s*\{[^}]*scrollbar-gutter:\s*stable/)
  })
  it('fixes the touch landscape Shoot grid to the viewport and scrolls inside it', () => {
    const css = read('./views/ShootView.vue')
    expect(css).toMatch(/height:\s*calc\(100dvh - 60px - 3px - var\(--banner/)
    expect(css).toMatch(/\.side-area\s*\{[^}]*overflow-y:\s*auto/)
    expect(css).toMatch(/\.film-area\s*\{[^}]*overflow-y:\s*auto/)
  })
})
