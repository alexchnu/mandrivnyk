import { defineConfig } from '@playwright/test'

// End-to-end tests run against a started stack (API on :8010 with at least one imported city
// and the client on :5173). PW_CHROMIUM may point to an already installed Chromium binary.
export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.PLANNER_URL ?? 'http://127.0.0.1:5173',
    viewport: { width: 1440, height: 900 },
    locale: 'uk-UA',
    timezoneId: 'Europe/Kyiv',
    launchOptions: {
      // native date and time inputs follow the browser language; the full Chromium (PW_CHROMIUM)
      // takes it from the environment, the headless shell ignores it
      args: ['--lang=uk-UA'],
      env: { ...process.env, LANG: 'uk_UA.UTF-8', LANGUAGE: 'uk' },
      ...(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {}),
    },
    screenshot: 'only-on-failure',
  },
})
