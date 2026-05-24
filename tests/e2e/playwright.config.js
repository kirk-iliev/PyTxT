const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const repoRoot = path.resolve(__dirname, '..', '..');

module.exports = defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  timeout: 30000,
  expect: { timeout: 5000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  webServer: {
    command: `${repoRoot}/.venv/bin/python -m pytxt`,
    url: 'http://127.0.0.1:8008',
    reuseExistingServer: true,
    timeout: 15000,
    env: {
      PYTXT_USE_SYNTHETIC_READER: '1',
    },
    cwd: repoRoot,
  },
  use: {
    baseURL: 'http://127.0.0.1:8008',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});
