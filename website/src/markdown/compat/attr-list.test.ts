import { describe, expect, it } from 'vitest';
import { remarkAttrList } from './attr-list';
import { render } from './test-utils';

describe('MkDocs attribute lists', () => {
    it('keeps native image attributes and drops MkDocs classes', async () => {
        const html = await render('![x](a.png){ .skip-lightbox loading=lazy }', [remarkAttrList]);
        expect(html).toContain('<img src="a.png" alt="x" loading="lazy">');
        expect(html).not.toContain('skip-lightbox');
        expect(html).not.toContain('{');
    });

    it('handles widget thumbnails, link classes and explicit heading ids', async () => {
        const html = await render('![signal_viewer](a.png){ .widget-thumb loading="lazy" width=480 }\n\n[Go](start.md){ .md-button }\n\n### Outlet { #output }', [remarkAttrList]);
        expect(html).toContain('loading="lazy" width="480"');
        expect(html).toContain('<a href="start.md">Go</a>');
        expect(html).toContain('<h3 id="output">Outlet</h3>');
        expect(html).not.toContain('.widget-thumb');
    });

    it('does not reinterpret ordinary braces or code samples', async () => {
        expect(await render('Text { target = "rig.mode" }.\n\n`![x](a.png){ loading=lazy }`', [remarkAttrList])).toContain('Text { target =');
    });
});
