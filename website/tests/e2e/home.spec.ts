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
    await expect(page.locator('[data-record-label]')).toHaveText('Pinch');
    await expect(page.locator('[data-confidence]')).toHaveText('0.91');
    await page.waitForTimeout(4100);
    await expect(prediction(page)).toHaveText('Pinch');
});

test('hero exposes Rest, Fist, Pinch and Index in order and holds each prediction', async ({ page }) => {
    await page.goto(home);
    await expect(page.locator('[data-gesture]')).toHaveText(['Rest', 'Fist', 'Pinch', 'Index']);
    for (const [gesture, confidence] of [['Rest', '0.97'], ['Fist', '0.94'], ['Pinch', '0.91'], ['Index', '0.88']]) {
        const chip = page.getByRole('button', { name: gesture, exact: true });
        await chip.click();
        await expect(prediction(page)).toHaveText(gesture);
        await expect(chip).toHaveAttribute('aria-pressed', 'true');
        await expect(page.locator('[data-confidence]')).toHaveText(confidence);
        await expect(page.locator('[data-record-label]')).toHaveText(gesture);
    }
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
    // Load/idle mounting and font-driven ResizeObserver delivery must finish
    // before comparing the still; panel text is available before canvas setup.
    await expect.poll(() => canvasHasSignal(page)).toBe(true);
    await page.evaluate(async () => {
        await document.fonts.ready;
        await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    });
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

for (const width of [390, 768, 1024, 1208]) {
    test(`hero stacks the panels below the copy at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(home);
        const copy = await page.locator('.hero-copy').boundingBox();
        const panels = await page.locator('[data-panels]').boundingBox();
        expect(panels!.y).toBeGreaterThanOrEqual(copy!.y + copy!.height);
    });
}

for (const width of [1209, 1280, 1440]) {
    test(`hero puts the panels beside the copy at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(home);
        await page.evaluate(() => document.fonts.ready);
        const copy = await page.locator('.hero-copy').boundingBox();
        const panels = await page.locator('[data-panels]').boundingBox();
        expect(panels!.y).toBeCloseTo(copy!.y, 0);
        expect(panels!.x).toBeGreaterThanOrEqual(copy!.x + copy!.width);
    });
}

for (const width of [390, 768]) {
    test(`stacked field fills an unattenuated band behind the panels at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto(home);
        await page.evaluate(() => document.fonts.ready);
        const canvas = page.locator('[data-signal-field]');
        await expect(canvas).toHaveCount(1);
        const field = await canvas.boundingBox();
        const panels = await page.locator('[data-panels]').boundingBox();
        const hero = await page.locator('.home-hero').boundingBox();
        const scrim = await page.locator('.hero-scrim').boundingBox();
        expect(field!.y).toBeCloseTo(panels!.y, 0);
        expect(field!.y + field!.height).toBeGreaterThanOrEqual(hero!.y + hero!.height - 1);
        expect(scrim!.y + scrim!.height).toBeLessThanOrEqual(panels!.y + 1);
        const centre = { x: panels!.x + panels!.width / 2, y: panels!.y + panels!.height / 2 };
        expect(centre.x).toBeGreaterThanOrEqual(field!.x);
        expect(centre.x).toBeLessThanOrEqual(field!.x + field!.width);
        // The mask is fully opaque after the first 48 px, including the centre.
        await expect(canvas).toHaveCSS('mask-image', /^linear-gradient\(rgba\(0, 0, 0, 0\), rgb\(\d+, \d+, \d+\) 48px\)$/);
        expect(centre.y).toBeGreaterThan(field!.y + 48);
        expect(centre.y).toBeLessThan(field!.y + field!.height);
        await expect(canvas).toHaveCSS('opacity', '1');
    });
}

test('phone hero copy is covered by a uniform scrim with AA body contrast', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(home);
    const scrim = page.locator('.hero-scrim');
    const backdrop = await scrim.boundingBox();
    // All of the copy, including the headline, install line and buttons, must
    // remain inside the attenuated region, away from any full-strength field.
    for (const selector of ['h1', '.hero-copy']) {
        const copy = await page.locator(selector).boundingBox();
        expect(copy!.x).toBeGreaterThanOrEqual(backdrop!.x);
        expect(copy!.y).toBeGreaterThanOrEqual(backdrop!.y);
        expect(copy!.x + copy!.width).toBeLessThanOrEqual(backdrop!.x + backdrop!.width);
        expect(copy!.y + copy!.height).toBeLessThanOrEqual(backdrop!.y + backdrop!.height);
    }
    await expect(scrim).toHaveCSS('background-image', 'none');
    const { opacity, contrast } = await scrim.evaluate(element => {
        const ctx = document.createElement('canvas').getContext('2d')!;
        function rgba(css: string) {
            ctx.clearRect(0, 0, 1, 1);
            ctx.fillStyle = css;
            ctx.fillRect(0, 0, 1, 1);
            return Array.from(ctx.getImageData(0, 0, 1, 1).data, value => value / 255);
        }
        const overlay = rgba(getComputedStyle(element).backgroundColor);
        const ink = rgba(getComputedStyle(document.querySelector('.hero-copy > p:nth-of-type(2)')!).color);
        // White is brighter than any trace, including additive intersections.
        const background = overlay.slice(0, 3).map(channel => channel * overlay[3] + 1 - overlay[3]);
        const foreground = background.map((channel, i) => ink[i] * ink[3] + channel * (1 - ink[3]));
        const luminance = (rgb: number[]) => rgb.map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
            .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
        return { opacity: overlay[3], contrast: (luminance(foreground) + 0.05) / (luminance(background) + 0.05) };
    });
    expect(opacity).toBeGreaterThanOrEqual(0.95);
    expect(contrast).toBeGreaterThanOrEqual(4.5);
});

for (const width of [320, 390, 768]) {
    test(`header links do not overlap and remain keyboard reachable at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto(home);
        const links = page.getByRole('navigation', { name: 'Main', exact: true }).getByRole('link');
        const boxes = await links.evaluateAll(elements => elements.map(element => {
            const { x, y, width, height } = element.getBoundingClientRect();
            return { x, y, width, height, name: element.getAttribute('aria-label') ?? element.textContent };
        }));
        for (const [i, box] of boxes.entries()) {
            expect(box.x).toBeGreaterThanOrEqual(0);
            expect(box.x + box.width).toBeLessThanOrEqual(width);
            for (const other of boxes.slice(i + 1)) {
                const overlaps = box.x < other.x + other.width && box.x + box.width > other.x
                    && box.y < other.y + other.height && box.y + box.height > other.y;
                expect(overlaps, `${box.name} overlaps ${other.name}`).toBe(false);
            }
        }
        await page.keyboard.press('Tab'); // Skip to content.
        for (const link of await links.all()) {
            await page.keyboard.press('Tab');
            await expect(link).toBeFocused();
            await expect(link).toBeInViewport();
        }
    });
}

test('Hello EMG ships a sized WebP in tens of kilobytes', async ({ page }) => {
    await page.goto(home);
    const image = page.getByRole('img', { name: 'Hello EMG app with SignalViewer and RecordingControls in the dark theme' });
    await image.scrollIntoViewIfNeeded();
    await expect(image).toHaveAttribute('width', '720');
    expect(Number(await image.getAttribute('height'))).toBeGreaterThan(0);
    const response = await page.request.get(await image.getAttribute('src') ?? '');
    expect(response.ok()).toBe(true);
    expect(response.headers()['content-type']).toContain('image/webp');
    expect((await response.body()).length).toBeLessThan(80_000);
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
    // The hero and the Playground section both offer it under the same name.
    const playgroundLinks = page.getByRole('link', { name: 'Open the Playground', exact: true });
    await expect(playgroundLinks).toHaveCount(2);
    for (const link of await playgroundLinks.all()) await expect(link).toHaveAttribute('href', '/MyoGestic/playground/');
    await expect(page.getByRole('link', { name: 'Get started', exact: true })).toHaveAttribute('href', '/MyoGestic/getting-started/');
    await expect(page.getByRole('link', { name: 'Search ⌘K in the docs' })).toHaveAttribute('href', '/MyoGestic/getting-started/');
    const version = readFileSync('../pyproject.toml', 'utf8').match(/^version\s*=\s*"([^"]+)"/m)![1];
    await expect(nav.getByRole('link', { name: /GitHub/ })).toHaveText(`GitHub · ${version}`);
    await expect(page.getByText('The background shows 64 channels of synthetic EMG.')).toBeVisible();
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

test('protocol cards copy their exact run command and link to real guides', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto(home);
    const button = page.getByRole('button', { name: 'Copy the myocontrol.py command' });
    await button.click();
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText()))
        .toBe('uv run --extra examples --extra grpc python examples/start_here/myocontrol.py');
    await expect(button).toHaveText('Copied');
    await expect(page.getByRole('link', { name: 'Read the guide →' })).toHaveCount(3);
    await expect(page.getByRole('link', { name: 'Quattrocento', exact: true }))
        .toHaveAttribute('href', '/MyoGestic/how-to/connect-otb-devices/#quattrocento-ethernet');
});

test('search shortcut follows the documented docs fallback', async ({ page }) => {
    await page.route('https://context7.com/widget.js', route => route.abort());
    await page.goto(home);
    await page.keyboard.press('Control+k');
    await expect(page).toHaveURL(/\/MyoGestic\/getting-started\/$/);
});
