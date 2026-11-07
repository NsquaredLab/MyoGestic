import { expect, test } from '@playwright/test';
import { ASK_SEARCH, ASK_SITE_KEY } from '../../src/context7-ask.mjs';

const escaped = ASK_SEARCH.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

for (const path of ['/MyoGestic/', '/MyoGestic/getting-started/', '/MyoGestic/404.html']) {
    test(`Context7 Ask tag and hidden note are served on ${path}`, async ({ request, page }) => {
        const html = await (await request.get(path, { failOnStatusCode: false })).text();
        expect(html).toMatch(new RegExp(`<meta name="context7-site-verification" content="${ASK_SITE_KEY}"\\s*/?>`));
        expect(html).toMatch(/<body[^>]*>\s*<blockquote data-context7-ask="true" aria-hidden="true" class="sr-only"[^>]*>\s*<h2>Search<\/h2>/);
        expect(html).toContain(escaped);
        await page.goto(path);
        const box = await page.locator('[data-context7-ask]').boundingBox();
        expect(box!.width).toBeLessThanOrEqual(1);
        expect(box!.height).toBeLessThanOrEqual(1);
    });
}

test('llms.txt carries the Context7 Ask search section after the summary', async ({ request }) => {
    const text = await (await request.get('/MyoGestic/llms.txt')).text();
    expect(text).toMatch(/^# MyoGestic\n\n(?:> .*\n)+\n## Search\n\n/);
    expect(text).toContain(ASK_SEARCH);
});
