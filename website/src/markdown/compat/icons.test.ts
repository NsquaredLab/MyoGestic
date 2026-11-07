import { describe, expect, it } from 'vitest';
import { remarkIcons } from './icons';
import { remarkAttrList } from './attr-list';
import { render } from './test-utils';

describe('icon shortcodes', () => {
    it('renders the API card and link icons without class attributes leaking into text', async () => {
        const html = await render(':material-application-braces-outline:{ .lg .middle } __Core__\n\n[:octicons-arrow-right-24: Core API](core.md)', [remarkIcons, remarkAttrList]);
        expect(html.match(/<svg class="mg-icon" aria-hidden="true"/g)).toHaveLength(2);
        expect(html).toContain('<a href="core.md"><svg');
        expect(html).not.toContain('.middle');
        expect(html).not.toContain(':material-');
    });

    it('fails with the page and unknown shortcode', async () => {
        await expect(render(':material-no-such-icon:', [remarkIcons])).rejects.toThrow('/docs/example.md:1: unknown icon :material-no-such-icon:');
    });

    it('preserves code examples', async () => {
        expect(await render('`:material-no-such-icon:`\n\n```md\n:octicons-nope:\n```', [remarkIcons])).toContain(':material-no-such-icon:');
    });
});
