import { expect, test, type Page } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

// CI builds a fresh wheel before the gate. Website-only runs may omit it.
const hasWheel = existsSync('dist/playground/wheels/manifest.json');
test.skip(!hasWheel, 'Build the playground wheel + manifest to run the browser loop');
test.use({
    launchOptions: {
        args: process.platform === 'darwin'
            ? ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=metal'] : [],
    },
});

async function state(page: Page) {
    return JSON.parse(await page.locator('body').getAttribute('data-mg-state') ?? '{}');
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    test(`Connect → Record → Train → Predict at ${viewport.width}px`, async ({ page }, testInfo) => {
        test.setTimeout(240_000);
        await page.setViewportSize(viewport);
        const phone = viewport.width < 1100;
        const errors: string[] = [];
        page.on('pageerror', error => errors.push(String(error)));
        page.on('console', message => {
            if (message.type() === 'error') errors.push(message.text());
        });
        const capture = async (step: string) => {
            const name = `playground-v2-${viewport.width}x${viewport.height}-${step}.png`;
            await page.screenshot({ path: process.env.MG_PLAYGROUND_SCREEN_DIR
                ? resolve(process.env.MG_PLAYGROUND_SCREEN_DIR, name) : testInfo.outputPath(name) });
        };
        const panelClick = async (x: number, y: number) => {
            const [left, top, width, height] = (await state(page)).panels.step;
            expect(x).toBeLessThan(width);
            expect(y).toBeLessThan(height);
            expect(top + y).toBeLessThan(viewport.height);
            await page.mouse.click(left + x, top + y);
        };
        const openStep = async (index: number) => {
            const current = (await state(page)).step;
            // The real AppHeader compacts inactive phone steps to their number/check.
            const phoneTargets: Record<string, number[]> = {
                Connect: [180, 230, 248, 266],
                Record: [166, 207, 247, 265],
                Train: [166, 184, 223, 265],
                Predict: [166, 184, 202, 244],
            };
            await page.mouse.click(phone ? phoneTargets[current][index] : [275, 384, 484, 582][index], 42);
            await expect.poll(async () => (await state(page)).step).toBe(['Connect', 'Record', 'Train', 'Predict'][index]);
        };

        await page.goto('/MyoGestic/playground/');
        await expect(page.locator('#loader')).toHaveCount(0, { timeout: 180_000 });
        await expect.poll(async () => (await state(page)).step).toBe('Connect');
        const initial = await state(page);
        expect(initial.participant).toBe('P-DEMO');
        expect(initial.connected).toBe(false);
        expect(initial.trained).toBe(false);
        const p = initial.panels;
        expect(Object.keys(p).sort()).toEqual(['header', 'log', 'sessions', 'signal', 'status', 'step']);
        if (phone) {
            expect(p.signal[1]).toBeLessThan(p.step[1]);
            expect(p.step[1]).toBeLessThan(p.sessions[1]);
            expect(p.sessions[1]).toBeLessThan(p.log[1]);
            for (const rect of Object.values(p) as number[][]) expect(rect[0] + rect[2]).toBeLessThanOrEqual(390);
        } else {
            expect(p.step[2]).toBe(400);
            expect(p.signal[0] + p.signal[2]).toBeLessThan(p.step[0]);
            expect(p.sessions[0]).toBe(p.step[0]);
            expect(p.log[1]).toBeGreaterThan(p.signal[1]);
        }
        const docs = await page.locator('#back-to-docs').boundingBox();
        expect(docs!.y).toBeGreaterThanOrEqual(p.header[1]);
        expect(docs!.y + docs!.height).toBeLessThanOrEqual(p.header[1] + p.header[3]);
        await capture('connect');
        await panelClick(phone ? 177 : 200, 89); // DevicePicker Connect
        await expect.poll(async () => (await state(page)).connected).toBe(true);
        await capture('connected');

        await openStep(1);
        await capture('record');
        for (const [index, gesture] of ['Rest', 'Fist', 'Pinch'].entries()) {
            await panelClick(phone ? [90, 250, 90][index] : [76, 200, 324][index], phone && index === 2 ? 130 : 78);
            await expect.poll(async () => (await state(page)).gesture).toBe(gesture);
            await expect.poll(async () => (await state(page)).take).toBe('idle');
            await panelClick(phone ? 170 : 200, phone ? 275 : 224); // timed Record
            await expect.poll(async () => (await state(page)).take).toBe('warmup');
            await capture(`record-${gesture.toLowerCase()}-warmup`);
            await expect.poll(async () => (await state(page)).recording).toBe(true);
            await expect.poll(async () => (await state(page)).take).toBe('recording');
            await capture(`record-${gesture.toLowerCase()}-capturing`);
            if (index === 1) await openStep(2); // timed capture must advance off-step
            await expect.poll(async () => (await state(page)).recording, { timeout: 10_000 }).toBe(false);
            await expect.poll(async () => (await state(page)).take).toBe('saved');
            await expect.poll(async () => (await state(page)).sessions.total).toBe(index + 1);
            expect((await state(page)).sessions.selected).toBe(index + 1);
            expect((await state(page)).sessions.classes[gesture]).toBeGreaterThan(2.5);
            expect((await state(page)).sessions.paths[index]).toMatch(/\.mg\.zip$/);
            if (index === 1) await openStep(1);
        }
        await capture('record-saved');
        await openStep(2);
        await capture('train');
        await panelClick(phone ? 170 : 200, 75); // public TrainButton
        await expect.poll(async () => (await state(page)).trained).toBe(true);
        await expect.poll(async () => (await state(page)).state).toBe('idle');
        expect((await state(page)).metrics.takes).toBe(3);
        expect((await state(page)).metrics.windows).toBeGreaterThan(60);
        expect((await state(page)).metrics.accuracy).toBeGreaterThan(0.95);
        // Let the native success toasts expire so the review capture shows the
        // sessions, activity log and status bar as well as the fitted model.
        await page.waitForTimeout(6200);
        await capture('trained');

        await openStep(3);
        await capture('predict');
        await panelClick(phone ? 170 : 200, 47); // public PredictButton
        await expect.poll(async () => (await state(page)).state).toBe('predicting');
        await expect.poll(async () => (await state(page)).prediction).toBe('Pinch');
        for (const [index, gesture] of ['Rest', 'Fist', 'Pinch'].entries()) {
            await panelClick([38, 82, 132][index], 255);
            await expect.poll(async () => (await state(page)).gesture).toBe(gesture);
            await expect.poll(async () => (await state(page)).prediction, {
                timeout: 1500, intervals: [50],
            }).toBe(gesture);
            await page.waitForTimeout(250);
            expect((await state(page)).prediction).toBe(gesture);
            await capture(`predict-${gesture.toLowerCase()}`);
        }
        expect(errors).toEqual([]);
    });
}
