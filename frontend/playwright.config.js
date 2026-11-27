import { defineConfig } from '@playwright/test'

const PORT = 18765

// Layout tests: every view must fit the viewport without page scroll. The demo-camera server
// (scripts/e2e_server.py) serves frontend/dist, so build first (`make e2e` does).
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? 'line' : 'list',
  timeout: 20_000,
  expect: { timeout: 3_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    actionTimeout: 3_000,
    trace: 'off',
  },
  projects: [
    { name: 'touch', use: { viewport: { width: 1280, height: 800 }, hasTouch: true } },
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    command: `.venv/bin/python -m scripts.e2e_server ${PORT}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
