import { defineConfig } from '@playwright/test';

const port = Number(process.env.PLAYWRIGHT_PORT ?? 4325);
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
    testDir: './tests/e2e',
    outputDir: '../.superpowers/test-results',
    fullyParallel: true,
    workers: 2,
    use: {
        baseURL: origin,
        viewport: { width: 1440, height: 1000 },
        colorScheme: 'dark',
        trace: 'retain-on-failure',
    },
    webServer: {
        command: `npm run preview -- --host 127.0.0.1 --port ${port} --ignore-lock`,
        url: `${origin}/MyoGestic/getting-started/`,
        reuseExistingServer: !process.env.CI,
    },
});
