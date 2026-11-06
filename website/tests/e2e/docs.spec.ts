import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const start = '/MyoGestic/getting-started/';
const api = '/MyoGestic/api/core/';

// Keep the layout/accessibility suite independent of the third-party service.
// The dedicated integration test below loads the actual Context7 script.
test.beforeEach(async ({ page }) => {
    await page.route('https://context7.com/widget.js', route => route.abort());
});

test('getting started has one h1 in Instrument Serif', async ({ page }) => {
    await page.goto(start);
    await expect(page.locator('h1')).toHaveCount(1);
    await expect(page.locator('h1')).toHaveCSS('font-family', /^"Instrument Serif"/);
    await expect(page.getByRole('heading', { name: 'Home', exact: true })).toHaveCount(0);
    await expect(page.getByRole('navigation', { name: 'Sections' }).getByRole('link', { name: 'Get started' }))
        .toHaveAttribute('aria-current', 'page');
});

test('theme toggle switches to light and persists', async ({ page }) => {
    await page.goto(start);
    await page.getByRole('button', { name: 'Switch to light theme' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.getByRole('button', { name: 'Switch to dark theme' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('system preference decides first visit and follows later changes', async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: 'light' });
    const page = await context.newPage();
    await page.route('https://context7.com/widget.js', route => route.abort());
    await page.goto(start);
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await context.close();
});

for (const theme of ['dark', 'light'] as const) {
    test(`code blocks use the console colours in ${theme}`, async ({ page }) => {
        await page.emulateMedia({ colorScheme: theme });
        await page.goto(start);
        await expect(page.locator('pre').first()).toHaveCSS('background-color', 'rgb(19, 20, 22)');
        const frame = page.locator('.expressive-code .frame').first();
        await expect(frame.locator('.header')).toBeVisible();
        await expect(frame.locator('.copy button')).toBeVisible();
    });
    for (const path of [start, api]) {
        test(`axe: no serious or critical violations on ${path} in ${theme}`, async ({ page }) => {
            await page.emulateMedia({ colorScheme: theme });
            await page.goto(path);
            const result = await new AxeBuilder({ page }).analyze();
            expect(result.violations.filter(v => ['serious', 'critical'].includes(v.impact ?? ''))).toEqual([]);
        });
    }
}

test('phone width contains long signatures and parameter tables', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(api);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    // Stress the generated markup with a value wider than any current API table.
    await page.locator('.sl-markdown-content').evaluate(el => {
        el.insertAdjacentHTML('beforeend', `<pre class="mg-signature"><code>App(${('long_parameter: SomeType, ').repeat(20)})</code></pre>
            <div class="mg-params-scroll"><table class="mg-params"><thead><tr><th>Name</th><th>Type</th><th>Description</th><th>Default</th></tr></thead>
            <tbody><tr><td><code>${'parameter'.repeat(30)}</code></td><td><code>SomeType</code></td><td>Details</td><td><code>None</code></td></tr></tbody></table></div>`);
    });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    expect(await page.locator('.mg-signature').last().evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
    expect(await page.locator('.mg-params-scroll').last().evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    await expect(page.locator('#starlight__sidebar')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#starlight__sidebar')).not.toBeVisible();
});

for (const width of [1440, 390]) {
    test(`API parameter names and defaults stay whole at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto('/MyoGestic/api/ml/');
        await expect(page.locator('[id="myogestic.ml.Pipeline.app"]')).toHaveCount(0);
        const table = page.locator('.mg-params').first();
        await expect(table.locator('thead th').last()).toHaveText('Default');
        await expect(table.locator('thead th').last()).toHaveCSS('white-space', 'nowrap');
        const name = table.locator('tbody td:first-child code').filter({ hasText: /^predict_hz$/ });
        await expect(name).toHaveCSS('white-space', 'nowrap');
        await expect(table.locator('tbody td:nth-child(4) code').first()).toHaveCSS('white-space', 'nowrap');
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
        if (width === 390) {
            const scroller = page.getByRole('group', { name: 'Parameters for Pipeline', exact: true });
            expect(await scroller.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
            await scroller.focus();
            await page.keyboard.press('ArrowRight');
            await expect.poll(() => scroller.evaluate(el => el.scrollLeft)).toBeGreaterThan(0);
        }
    });
}

test('search opens with the keyboard and finds docs', async ({ page }) => {
    await page.goto(start);
    await page.keyboard.press('Control+k');
    await expect(page.getByRole('dialog', { name: 'Search' })).toBeVisible();
    await page.getByRole('textbox').fill('recording');
    await expect(page.locator('.pagefind-ui__result').first()).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Search' })).not.toBeVisible();
});

for (const width of [1440, 390]) {
    test(`ask the docs opens the actual closed-root Context7 chat at ${width}px`, async ({ page, request }) => {
        test.setTimeout(60000);
        const response = await request.get('https://context7.com/widget.js');
        expect(response.ok()).toBe(true);
        const body = await response.body();
        await page.unroute('https://context7.com/widget.js');
        await page.route('https://context7.com/widget.js', route => route.fulfill({ body, contentType: 'application/javascript' }));
        await page.setViewportSize({ width, height: 844 });
        await page.goto(start);
        await page.locator('#context7-widget[data-mg-ready]').waitFor({ state: 'attached' });
        expect(await page.locator('#context7-widget').evaluate(el => el.shadowRoot)).toBeNull();

        // CDP can inspect the real closed root without changing the widget's
        // production shadow mode or installing a test-only opening API.
        const cdp = await page.context().newCDPSession(page);
        const { root } = await cdp.send('DOM.getDocument', { depth: -1, pierce: true });
        const nodes: any[] = [];
        function walk(node: any) {
            nodes.push(node);
            [...(node.children ?? []), ...(node.shadowRoots ?? [])].forEach(walk);
        }
        walk(root);
        async function objectFor(className: string) {
            const node = nodes.find(node => {
                const i = node.attributes?.indexOf('class') ?? -1;
                return i >= 0 && node.attributes[i + 1].split(' ').includes(className);
            });
            expect(node, `Context7 element .${className}`).toBeTruthy();
            const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: node.backendNodeId });
            return object.objectId!;
        }
        async function inspect(objectId: string, fn: string) {
            const { result } = await cdp.send('Runtime.callFunctionOn', {
                objectId, functionDeclaration: fn, returnByValue: true,
            });
            return result.value;
        }
        const bubble = await objectFor('c7-bubble');
        const panel = await objectFor('c7-panel');
        const input = await objectFor('c7-input');
        const ax = await cdp.send('Accessibility.getPartialAXTree', { objectId: bubble });
        expect(ax.nodes[0].name?.value).toBe('Ask the docs');
        expect(await inspect(bubble, `function() { const s = getComputedStyle(this); return [s.backgroundColor, s.height]; }`))
            .toEqual(['rgb(36, 43, 54)', '44px']);
        const bounds = await inspect(bubble, `function() { const b = this.getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; }`);
        await page.mouse.click(bounds.x, bounds.y);
        await expect.poll(() => inspect(panel, `function() { return getComputedStyle(this).visibility; }`)).toBe('visible');
        await expect.poll(() => inspect(input, `function() { return this.getRootNode().activeElement === this; }`)).toBe(true);
        expect(await inspect(panel, `function() { return this.getBoundingClientRect().right; }`)).toBeLessThanOrEqual(width);
        await page.keyboard.press('Control+k');
        await expect(page.getByRole('dialog', { name: 'Search' })).not.toBeVisible();
        await page.keyboard.type('Stream');
        expect(await inspect(input, `function() { return this.value; }`)).toBe('Stream');
        await page.keyboard.press('Escape');
        await expect.poll(() => inspect(panel, `function() { return getComputedStyle(this).visibility; }`)).toBe('hidden');
        expect(await inspect(bubble, `function() { return this.getRootNode().activeElement === this; }`)).toBe(true);
    });
}
