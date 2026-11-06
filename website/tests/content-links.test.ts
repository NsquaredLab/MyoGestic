import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { visit } from 'unist-util-visit';
import { remarkContentLinks } from '../src/markdown/plugins';

async function urls(markdown: string, page = 'how-to/add-a-model.md') {
    const processor = unified().use(remarkParse).use(remarkContentLinks);
    const tree = await processor.run(processor.parse(markdown), {
        path: fileURLToPath(new URL(`../../docs/${page}`, import.meta.url)),
    });
    const result: string[] = [];
    visit(tree, (node) => {
        if ('url' in node && typeof node.url === 'string') result.push(node.url);
    });
    return result;
}

describe('docs links under the GitHub Pages base', () => {
    it('maps source-relative Markdown links to existing directory routes', async () => {
        expect(await urls('[ML](../api/ml.md#pipeline) [Guides](index.md) [Home](../index.md)'))
            .toEqual(['/MyoGestic/api/ml/#pipeline', '/MyoGestic/how-to/', '/MyoGestic/']);
    });

    it('uses the maintained README slugs and public static assets', async () => {
        expect(await urls('[OTB](../reference/otb/README.md) ![plot](../images/architecture.svg?raw=1)'))
            .toEqual(['/MyoGestic/reference/otb/', '/MyoGestic/images/architecture.svg?raw=1']);
    });

    it('preserves external links, local anchors and already based links', async () => {
        expect(await urls('[Web](https://example.org/a.md) [Here](#usage) [Docs](/MyoGestic/api/)'))
            .toEqual(['https://example.org/a.md', '#usage', '/MyoGestic/api/']);
    });

    it('resolves link definitions and source-relative directory links', async () => {
        expect(await urls('[API][api]\n\n[api]: ../api/\n\n[Playground](../playground/)'))
            .toEqual(['/MyoGestic/api/', '/MyoGestic/playground/']);
    });
});
