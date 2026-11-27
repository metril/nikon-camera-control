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
  'Security',
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
const KNOWN_FAILING = new Set([])

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
  // The e2e server pins a fixed target (seeded files) that /locations doesn't list, so present
  // it as the chosen drive: the Saved view needs a target, as on a real install.
  await page.route('**/api/v1/locations', async (route) => {
    const res = await route.fetch()
    const body = await res.json()
    body.locations = [
      ...body.locations,
      {
        id: 'fixed',
        kind: 'usb',
        name: 'Seeded',
        auto_mount: false,
        configured: true,
        present: true,
        mounted: true,
        supported: true,
        has_password: false,
        is_target: true,
        is_backup: false,
        size: 64e9,
        free: 32e9,
      },
    ]
    body.target_id = 'fixed'
    await route.fulfill({ response: res, json: body })
  })
  await page.reload()
  await page.getByRole('radio', { name: /seeded/i }).click()
  await control(page, /^select$/i).click({ timeout: 15000 })
  await expectFits(page)
})
