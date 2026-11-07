import { expect, test, type Page } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// CI writes the wheel before npm run ci; ordinary website-only runs can omit it.
const hasWheel = existsSync('dist/playground/wheels/manifest.json');
test.skip(!hasWheel, 'Build the playground wheel + manifest to run the browser loop');
test.use({
    viewport: { width: 1440, height: 900 },
    launchOptions: {
        args: process.platform === 'darwin'
            ? ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=metal'] : [],
    },
});

async function state(page: Page) {
    return JSON.parse(await page.locator('body').getAttribute('data-mg-state') ?? '{}');
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    test(`record, save, train and predict at ${viewport.width}px`, async ({ page }, testInfo) => {
        test.setTimeout(240_000);
        await page.setViewportSize(viewport);
        const phone = viewport.width < 720;
        const gestures = phone
            ? [['Rest', 108, 204], ['Fist', 252, 204], ['Pinch', 108, 258]] as const
            : [['Rest', 108, 213], ['Fist', 252, 213], ['Pinch', 108, 258]] as const;
        const capture = async (step: string) => {
            const name = `playground-${viewport.width}x${viewport.height}-${step}.png`;
            await page.screenshot({ path: process.env.MG_PLAYGROUND_SCREEN_DIR
                ? resolve(process.env.MG_PLAYGROUND_SCREEN_DIR, name) : testInfo.outputPath(name) });
        };
        const modelView = async (visible: boolean) => {
            if (!phone) return;
            // Scroll the outer ImGui child via its scrollbar, away from nested plots.
            await page.mouse.move(365, 600);
            await page.mouse.wheel(0, visible ? 650 : -2000);
            await page.waitForTimeout(300);
        };
        const errors: string[] = [];
        page.on('pageerror', error => errors.push(String(error)));
        page.on('console', message => {
            if (message.type() === 'error') errors.push(message.text());
        });
        await page.goto('/MyoGestic/playground/');
        await expect(page.locator('#loader')).toHaveCount(0, { timeout: 180_000 });
        await expect.poll(async () => (await state(page)).state).toBe('idle');
        await capture('ready');

        await page.mouse.click(178, phone ? 300 : 308); // Record Rest in the ImGui canvas.
        await expect.poll(async () => (await state(page)).recording).toBe(true);
        await expect.poll(async () => (await state(page)).take).toBe('recording');
        await page.waitForTimeout(2500); // collect stable windows per gesture
        await capture('recording-rest');
        for (const [gesture, x, y] of gestures.slice(1)) {
            await page.mouse.click(x, y);
            await expect.poll(async () => (await state(page)).gesture).toBe(gesture);
            await page.waitForTimeout(2500);
            await capture(`recording-${gesture.toLowerCase()}`);
        }
        await page.mouse.click(178, phone ? 300 : 308); // Stop in the same action row.
        await expect.poll(async () => (await state(page)).recording).toBe(false);
        await expect.poll(async () => (await state(page)).take).toBe('saved');
        await expect.poll(async () => (await state(page)).state).toBe('idle');
        await expect.poll(async () => (await state(page)).sessions.length).toBe(1);
        const saved = (await state(page)).sessions[0];
        expect(saved.name).toBe('session_01');
        for (const name of ['Rest', 'Fist', 'Pinch']) expect(saved.classes[name]).toBeGreaterThan(5);
        await modelView(true);
        await capture('stopped-session');

        await page.mouse.click(173, phone ? 477 : 543); // Train
        await expect.poll(async () => (await state(page)).trained).toBe(true);
        await expect.poll(async () => (await state(page)).state).toBe('idle');
        await capture('trained');
        await page.mouse.click(68, phone ? 510 : 573); // Predict
        await expect.poll(async () => (await state(page)).state).toBe('predicting');
        await expect.poll(async () => (await state(page)).prediction).toBe('Pinch');
        await capture('predicting-pinch');
        await modelView(false);
        for (const [gesture, x, y] of gestures) {
            await page.mouse.click(x, y);
            await expect.poll(async () => (await state(page)).gesture).toBe(gesture);
            await expect.poll(async () => (await state(page)).prediction, {
                timeout: 1200, intervals: [50],
            }).toBe(gesture);
            await page.waitForTimeout(300);
            expect((await state(page)).prediction).toBe(gesture);
            await modelView(true);
            await capture(`prediction-${gesture.toLowerCase()}`);
            await modelView(false);
        }
        expect(errors).toEqual([]);
    });
}
