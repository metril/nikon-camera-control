import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// jsdom does no layout, so guard the CSS contract that keeps the kiosk page from scrolling/shifting.
const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const rule = (css, selector) => {
  const esc = selector.replace(/[.[\]'=]/g, '\\$&')
  const m = css.match(new RegExp(`(?:^|\\n)${esc}\\s*\\{([^}]*)\\}`))
  return m ? m[1] : ''
}

describe('scroll layout', () => {
  const css = read('./style.css')

  it('reserves the root scrollbar gutter so pages do not shift', () => {
    expect(css).toMatch(/html\s*\{[^}]*scrollbar-gutter:\s*stable/)
  })
  it('fixes the touch landscape Shoot grid to the viewport and scrolls inside it', () => {
    const view = read('./views/ShootView.vue')
    expect(view).toMatch(/height:\s*calc\(100dvh - 60px - 3px - var\(--banner/)
    expect(view).toMatch(/\.side-area\s*\{[^}]*overflow-y:\s*auto/)
    expect(view).toMatch(/\.film-area\s*\{[^}]*overflow-y:\s*auto/)
  })
  it('the frame is exactly the viewport and clips overflow; the page body never scrolls', () => {
    const frame = rule(css, '.app-frame')
    expect(frame).toMatch(/height:\s*100dvh/)
    expect(frame).toMatch(/overflow:\s*hidden/)
    expect(rule(css, 'body')).toMatch(/overflow:\s*hidden/)
    expect(css).not.toMatch(/min-height:\s*100vh/)
  })
  it('.scroll-panel scrolls with a reserved thin gutter', () => {
    const panel = rule(css, '.scroll-panel')
    expect(panel).toMatch(/overflow:\s*auto/)
    expect(panel).toMatch(/scrollbar-gutter:\s*stable/)
    expect(panel).toMatch(/scrollbar-width:\s*thin/)
  })
  it('the on-screen keyboard shrinks the frame instead of padding a scrolling body', () => {
    expect(css).toMatch(/html\[data-osk-open\] \.app-frame\s*\{[^}]*--osk-h/)
  })
  it('App.vue uses the frame and a clipped, shrinkable main', () => {
    const app = read('./App.vue')
    expect(app).toContain('app-frame')
    expect(app).not.toMatch(/min-h-screen/)
    expect(app).toMatch(/\.main\s*\{[^}]*min-height:\s*0[^}]*overflow:\s*hidden/)
  })
})
