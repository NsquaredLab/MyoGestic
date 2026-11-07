import { describe, expect, it } from 'vitest';
import { rehypeHeadingIds } from './heading-ids';
import { remarkAttrList } from './attr-list';
import { render } from './test-utils';

describe('Python-Markdown heading ids', () => {
    it('matches punctuation, ASCII normalisation, Unicode whitespace and duplicates', async () => {
        const html = await render('## The one convention a device may not redefine\n\n## `Pipeline(app)` adds\n\n## Usage\n\n## Usage\n\n## Usage\n\n## Café — déjà vu!\n\n## A_B\n\n## 日本語', [], [rehypeHeadingIds]);
        for (const id of ['the-one-convention-a-device-may-not-redefine', 'pipelineapp-adds', 'usage', 'usage_1', 'usage_2', 'cafe-deja-vu', 'a_b', '_1']) expect(html).toContain(`id="${id}"`);
    });

    it('resets duplicate counters between documents', async () => {
        for (let i = 0; i < 2; i++) expect(await render('## Usage', [], [rehypeHeadingIds])).toContain('id="usage"');
    });

    it('preserves explicit legacy ids and API ids', async () => {
        const html = await render('### Outlet { #output }\n\n### Pipeline { #myogestic.ml.Pipeline }\n\n## Output', [remarkAttrList], [rehypeHeadingIds]);
        expect(html).toContain('<h3 id="output">Outlet</h3>');
        expect(html).toContain('id="myogestic.ml.Pipeline"');
        expect(html).toContain('<h2 id="output_1">Output</h2>');
    });
});
