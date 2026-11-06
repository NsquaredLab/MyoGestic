import { defineConfig } from '@playwright/test';

export default defineConfig({
    testDir: './tests/e2e',
    outputDir: '../.superpowers/test-results',
    fullyParallel: true,
    workers: 2,
    use: {
        baseURL: 'http://127.0.0.1:4325',
        viewport: { width: 1440, height: 1000 },
        colorScheme: 'dark',
        trace: 'retain-on-failure',
    },
    webServer: {
        command: 'npm run preview -- --host 127.0.0.1 --port 4325 --ignore-lock',
        url: 'http://127.0.0.1:4325/MyoGestic/getting-started/',
        reuseExistingServer: !process.env.CI,
    },
});
