import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:4173';

export default defineConfig({
    testDir: './tests/e2e',
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 0,
    workers: process.env.CI ? 2 : undefined,
    reporter: process.env.CI ? 'github' : 'list',
    use: {
        baseURL,
        trace: 'on-first-retry',
    },
    projects: [
        {
            name: 'chromium-mocked',
            testMatch: /.*\.spec\.js/,
            testIgnore: /.*\.docker\.spec\.js/,
            use: { ...devices['Desktop Chrome'] },
        },
        {
            name: 'chromium-docker',
            testMatch: /.*\.docker\.spec\.js/,
            use: { ...devices['Desktop Chrome'] },
        },
    ],
    webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
        ? undefined
        : {
            command: 'npm run preview -- --host 127.0.0.1 --port 4173',
            url: baseURL,
            reuseExistingServer: !process.env.CI,
            timeout: 120000,
        },
});
