import { describe, expect, it } from 'vitest';
import { remarkAdmonitions } from './admonitions';
import { remarkContentLinks } from '../plugins';
import { fileURLToPath } from 'node:url';
import { render } from './test-utils';

describe('MkDocs admonitions', () => {
    it('renders the standalone generator callout and its nested code fence', async () => {
        const html = await render('!!! note "Running the generator standalone"\n    The launcher runs:\n\n    ```bash\n    uv run python -m myogestic.tools.emg_generator\n    ```\n\nOutside.', [remarkAdmonitions]);
        expect(html).toContain('<aside class="mg-callout mg-callout--note">');
        expect(html).toContain('<p class="mg-callout__title">Running the generator standalone</p>');
        expect(html).toContain('<p>The launcher runs:</p>');
        expect(html).toContain('<code class="language-bash">uv run python -m myogestic.tools.emg_generator\n</code>');
        expect(html).toContain('</aside>\n<p>Outside.</p>');
    });

    it.each([['??? warning', '<details class="mg-callout mg-callout--warning">', 'Warning'], ['???+ tip', '<details class="mg-callout mg-callout--tip" open>', 'Tip']])('renders %s with the correct disclosure state', async (marker, opening, title) => {
        const html = await render(`${marker}\n    Body.`, [remarkAdmonitions]);
        expect(html).toContain(opening);
        expect(html).toContain(`<summary class="mg-callout__title">${title}</summary>`);
    });

    it('keeps Markdown in titles and bodies and handles nested callouts', async () => {
        const html = await render('!!! note "The key in `request.discrete` is your **address**, not the client\'s alias"\n    See [controls](../api/controls.md).\n\n    !!! tip\n        Nested.\n\n<!--docs:skip-->', [remarkAdmonitions]);
        expect(html).toContain('<code>request.discrete</code> is your <strong>address</strong>');
        expect(html).toContain('<aside class="mg-callout mg-callout--tip">');
        expect(html).toContain('<!--docs:skip-->');
    });

    it('leaves markers in fenced and indented code alone', async () => {
        const html = await render('```md\n!!! tip\n    example\n```\n\n    ??? note\n        code', [remarkAdmonitions]);
        expect(html).not.toContain('mg-callout');
    });

    it('exposes links in bodies to transforms registered before this plugin', async () => {
        const html = await render('!!! tip\n    [Core](api/core.md)', [remarkContentLinks, remarkAdmonitions], [], fileURLToPath(new URL('../../../../docs/getting-started.md', import.meta.url)));
        expect(html).toContain('href="/MyoGestic/api/core/"');
    });
});
