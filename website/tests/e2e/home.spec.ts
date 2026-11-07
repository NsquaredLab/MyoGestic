import { expect, test, chromium, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';

const home = '/MyoGestic/';
const prediction = (page: Page) => page.locator('[data-prediction]');

test('hero gesture chip holds the prediction', async ({ page }) => {
    await page.goto(home);
    const chip = page.getByRole('button', { name: 'Pinch', exact: true });
    await chip.click();
    await expect(prediction(page)).toHaveText('Pinch');
    await expect(chip).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: 'Record Pinch', exact: true })).toBeVisible();
    await expect(page.locator('[data-confidence]')).toHaveText('0.88');
    await page.waitForTimeout(4100);
    await expect(prediction(page)).toHaveText('Pinch');
});

test('auto chip resumes cycling', async ({ page }) => {
    await page.goto(home);
    await page.getByRole('button', { name: 'Pinch', exact: true }).click();
    await page.getByRole('button', { name: /^Auto/i }).click();
    await expect(prediction(page)).not.toHaveText('Pinch', { timeout: 3500 });
});

test('reduced motion shows a still frame', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(home);
    await expect(prediction(page)).toHaveText('Fist');
    const pixels = await page.locator('[data-signal-field]').evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
    await page.waitForTimeout(4100);
    await expect(prediction(page)).toHaveText('Fist');
    expect(await page.locator('[data-signal-field]').evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL())).toBe(pixels);
});

async function canvasHasSignal(page: Page) {
    return page.locator('[data-signal-field]').evaluate(async (canvas: HTMLCanvasElement) => {
        const image = new Image();
        image.src = canvas.toDataURL();
        await image.decode();
        const copy = document.createElement('canvas');
        copy.width = image.width;
        copy.height = image.height;
        const ctx = copy.getContext('2d')!;
        ctx.drawImage(image, 0, 0);
        const pixels = ctx.getImageData(0, 0, copy.width, copy.height).data;
        for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i] > 25 || pixels[i + 1] > 26 || pixels[i + 2] > 28) return true;
        }
        return false;
    });
}

test('canvas draws without WebGL', async ({ baseURL }) => {
    const browser = await chromium.launch({ args: ['--disable-webgl'] });
    try {
        const page = await browser.newPage();
        await page.goto(`${baseURL}${home}`);
        await expect.poll(() => canvasHasSignal(page)).toBe(true);
    } finally {
        await browser.close();
    }
});

test('context loss replaces the canvas and keeps controls and resizing working', async ({ page }) => {
    await page.goto(home);
    const originalCanvas = await page.locator('[data-signal-field]').elementHandle();
    const hadWebGL = await page.locator('[data-signal-field]').evaluate((canvas: HTMLCanvasElement) => {
        const gl = canvas.getContext('webgl2');
        const extension = gl?.getExtension('WEBGL_lose_context');
        if (!extension) return false;
        extension.loseContext();
        return true;
    });
    test.skip(!hadWebGL, 'WebGL context loss is unavailable on this browser');
    await expect.poll(() => originalCanvas!.evaluate(canvas => canvas.isConnected)).toBe(false);
    await page.getByRole('button', { name: 'Pinch', exact: true }).click();
    await expect(prediction(page)).toHaveText('Pinch');
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.locator('[data-signal-field]').evaluate((canvas: HTMLCanvasElement) => canvas.width)).toBe(390);
    await expect.poll(() => canvasHasSignal(page)).toBe(true);
});

test('phone width contains the page and puts the headline above the panels', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(home);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    const headline = await page.locator('h1').boundingBox();
    const panels = await page.locator('[data-panels]').boundingBox();
    expect(headline!.y).toBeLessThan(844);
    expect(headline!.y + headline!.height).toBeLessThan(panels!.y);
});

for (const width of [1440, 390]) {
    test(`axe: no serious or critical violations at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(home);
        const result = await new AxeBuilder({ page }).analyze();
        expect(result.violations.filter(v => ['serious', 'critical'].includes(v.impact ?? ''))).toEqual([]);
    });
}

test('homepage is dark even with a light preference and has no theme toggle', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto(home);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('h1')).toHaveCSS('font-family', /^"Instrument Serif"/);
    await expect(page.locator('starlight-theme-select, [aria-label*="theme" i]')).toHaveCount(0);
});

test('links and package version match the integrated site', async ({ page }) => {
    await page.goto(home);
    const nav = page.getByRole('navigation', { name: 'Main', exact: true });
    for (const [label, href] of [
        ['Docs', '/MyoGestic/getting-started/'],
        ['Widgets', '/MyoGestic/widget-gallery/'],
        ['Playground', '/MyoGestic/playground/'],
        ['API', '/MyoGestic/api/'],
        ['Changelog', 'https://github.com/NsquaredLab/MyoGestic/blob/main/CHANGELOG.md'],
    ]) await expect(nav.getByRole('link', { name: label, exact: true })).toHaveAttribute('href', href);
    await expect(page.getByRole('link', { name: 'Open the Playground', exact: true })).toHaveAttribute('href', '/MyoGestic/playground/');
    await expect(page.getByRole('link', { name: 'Get started', exact: true })).toHaveAttribute('href', '/MyoGestic/getting-started/');
    await expect(page.getByRole('link', { name: 'Search ⌘K in the docs' })).toHaveAttribute('href', '/MyoGestic/getting-started/');
    const version = readFileSync('../pyproject.toml', 'utf8').match(/^version\s*=\s*"([^"]+)"/m)![1];
    await expect(nav.getByRole('link', { name: /GitHub/ })).toHaveText(`GitHub · ${version}`);
    await expect(page.getByText('Behind this page: 64 channels of synthetic EMG, drawn live')).toBeVisible();
});

test('install and BibTeX buttons copy their exact content and announce success', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto(home);
    await page.getByRole('button', { name: 'Copy install command' }).click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('pip install myogestic');
    await expect(page.locator('[data-install-status]')).toHaveText('Copied');
    await page.getByRole('button', { name: 'Copy BibTeX' }).click();
    const bibtex = readFileSync('../README.md', 'utf8').match(/```bibtex\n([\s\S]*?)\n```/)![1];
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(bibtex);
    await expect(page.locator('[data-cite-status]')).toHaveText('Copied');
});

test('search shortcut follows the documented docs fallback', async ({ page }) => {
    await page.route('https://context7.com/widget.js', route => route.abort());
    await page.goto(home);
    await page.keyboard.press('Control+k');
    await expect(page).toHaveURL(/\/MyoGestic\/getting-started\/$/);
});
