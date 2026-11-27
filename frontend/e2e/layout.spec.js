// Scroll-free layout contract: at 1280x800 (touch kiosk) and 1440x900 (desktop browser) no view
// may scroll the page or overflow horizontally. Only inner `.scroll-panel` lists may scroll.
import { test, expect } from '@playwright/test'

const TABS = ['shoot', 'timelapse', 'gallery', 'settings']
const SHOOT_MODES = ['Single', 'Bracket', 'Bulb', 'Stack']
const SETTINGS_SECTIONS = [
  'Display',
  'Capture',
  'Storage',
  'Camera',
  'Live view',
  'Time-lapse',
  'Video',
  'Media',
  'Advanced',
  'Demo camera',
  ['API key', /api key|security/i],
  'About',
]
const TIMELAPSE_TABS = ['Timing', 'Bracket', 'Run', 'Sessions'] // touch only

// Control by accessible name, whether it is built as a tab, button or radio.
const control = (page, name, scope = page) => {
  const o = { name, exact: typeof name === 'string' }
  return scope
    .getByRole('tab', o)
    .or(scope.getByRole('button', o))
    .or(scope.getByRole('radio', o))
    .first()
}

async function open(page, tab, touch) {
  await page.goto(`/?layout=${touch ? 'touch' : 'desktop'}#/${tab}`)
  await page.getByRole('main').or(page.locator('#app')).first().waitFor()
  await page.waitForLoadState('load')
  await page.waitForTimeout(500) // let data fetches and fonts settle
}

async function expectFits(page) {
  const m = await page.evaluate(() => ({
    sh: document.scrollingElement.scrollHeight,
    ih: innerHeight,
    sw: document.scrollingElement.scrollWidth,
    iw: innerWidth,
  }))
  expect(m.sh, `page scrolls vertically (${m.sh} > ${m.ih})`).toBeLessThanOrEqual(m.ih)
  expect(m.sw, `page overflows horizontally (${m.sw} > ${m.iw})`).toBeLessThanOrEqual(m.iw)
}

// The layout rework has not landed yet. Cases listed here fail on today's code and are marked
// test.fail() so CI stays green; remove an entry once its view is reworked (a passing
// test.fail() case fails the run, which prompts exactly that).
// Key: `${project}: ${title}`.
const KNOWN_FAILING = new Set([
  'touch: timelapse fits the viewport',
  'touch: settings fits the viewport',
  'touch: settings section Display fits the viewport',
  'touch: settings section Capture fits the viewport',
  'touch: settings section Storage fits the viewport',
  'touch: settings section Camera fits the viewport',
  'touch: settings section Live view fits the viewport',
  'touch: settings section Time-lapse fits the viewport',
  'touch: settings section Video fits the viewport',
  'touch: settings section Media fits the viewport',
  'touch: settings section Advanced fits the viewport',
  'touch: settings section Demo camera fits the viewport',
  'touch: settings section API key fits the viewport',
  'touch: settings section About fits the viewport',
  'touch: timelapse tab Timing fits the viewport',
  'touch: timelapse tab Bracket fits the viewport',
  'touch: timelapse tab Run fits the viewport',
  'touch: timelapse tab Sessions fits the viewport',
  'touch: gallery selection mode fits the viewport',
  'desktop: timelapse fits the viewport',
  'desktop: settings fits the viewport',
  'desktop: settings section Display fits the viewport',
  'desktop: settings section Capture fits the viewport',
  'desktop: settings section Storage fits the viewport',
  'desktop: settings section Camera fits the viewport',
  'desktop: settings section Live view fits the viewport',
  'desktop: settings section Time-lapse fits the viewport',
  'desktop: settings section Video fits the viewport',
  'desktop: settings section Media fits the viewport',
  'desktop: settings section Advanced fits the viewport',
  'desktop: settings section Demo camera fits the viewport',
  'desktop: settings section API key fits the viewport',
  'desktop: settings section About fits the viewport',
  'desktop: gallery selection mode fits the viewport',
])

let touch = false
test.beforeEach(({ hasTouch }, info) => {
  touch = hasTouch
  if (KNOWN_FAILING.has(`${info.project.name}: ${info.title}`)) {
    test.fail(true, 'layout rework pending: view still scrolls or lacks the new controls')
  }
})

for (const tab of TABS) {
  test(`${tab} fits the viewport`, async ({ page }) => {
    await open(page, tab, touch)
    await expectFits(page)
  })
}

for (const mode of SHOOT_MODES) {
  test(`shoot mode ${mode} fits the viewport`, async ({ page }) => {
    await open(page, 'shoot', touch)
    await control(page, mode).click()
    await expectFits(page)
  })
}

for (const entry of SETTINGS_SECTIONS) {
  const [section, name] = Array.isArray(entry) ? entry : [entry, entry]
  test(`settings section ${section} fits the viewport`, async ({ page }) => {
    await open(page, 'settings', touch)
    await control(page, name, page.getByRole('navigation', { name: 'Settings sections' })).click()
    await expectFits(page)
  })
}

for (const t of TIMELAPSE_TABS) {
  test(`timelapse tab ${t} fits the viewport`, async ({ page }) => {
    test.skip(!touch, 'desktop shows every time-lapse panel at once')
    await open(page, 'timelapse', touch)
    await control(page, t).click()
    await expectFits(page)
  })
}

test('gallery selection mode fits the viewport', async ({ page }) => {
  await open(page, 'gallery', touch)
  await control(page, /^select/i).click()
  await expectFits(page)
})
