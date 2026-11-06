import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { remarkGridCards } from './grid-cards';
import { remarkContentLinks } from '../plugins';
import { render } from './test-utils';

describe('Markdown HTML containers and grid cards', () => {
    it('renders one card per list item with Markdown paragraphs and links', async () => {
        const html = await render('<div class="grid cards" markdown>\n\n-   __Core__\n\n    ---\n\n    App lifecycle.\n\n    [Core API](core.md)\n\n-   __Widgets__\n\n    ![SignalViewer](../images/widgets/signal_viewer.png)\n\n</div>', [remarkGridCards, remarkContentLinks], [], fileURLToPath(new URL('../../../../docs/api/index.md', import.meta.url)));
        expect(html).toContain('<div class="mg-cards">');
        expect(html.match(/<div class="mg-card">/g)).toHaveLength(2);
        expect(html).toContain('<strong>Core</strong>');
        expect(html).toContain('<p>App lifecycle.</p>');
        expect(html).toContain('href="/MyoGestic/api/core/"');
        expect(html).not.toContain('<ul>');
    });

    it('parses gallery navigation Markdown even without a blank after the opening tag', async () => {
        const html = await render('<div class="gallery-nav" markdown>\n[Signal viewers](#signal-viewers)\n[Session shell](#session-shell)\n</div>', [remarkGridCards]);
        expect(html).toContain('<div class="gallery-nav">');
        expect(html).toContain('<a href="#signal-viewers">Signal viewers</a>');
        expect(html).not.toContain(' markdown');
    });

    it('keeps ordinary lists and HTML code examples unchanged', async () => {
        const html = await render('- normal\n\n```html\n<div class="grid cards" markdown>\n```', [remarkGridCards]);
        expect(html).toContain('<ul>');
        expect(html).not.toContain('class="mg-cards"');
    });
});
