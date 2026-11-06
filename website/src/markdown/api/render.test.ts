import { describe, expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkRehype from 'remark-rehype';
import rehypeRaw from 'rehype-raw';
import { toHtml } from 'hast-util-to-html';
import { renderSymbol, type ApiData } from './render';

const api: ApiData = {
    pages: {}, inventory: { 'myogestic.Item': '/MyoGestic/api/core/#myogestic.Item' },
    symbols: { 'myogestic.Item': {
        kind: 'class', name: 'Item', path: 'myogestic.Item',
        signature: 'Item(value: list[str] | None = None)', bases: ['Base'], labels: [], members: [],
        docstring: [
            { kind: 'text', value: 'An **item** with `code`.\n\n[Guide](../concepts/streams.md) and [Item][myogestic.Item].\n\n- First\n- Second' },
            { kind: 'parameters', value: [{ name: 'value', annotation: 'list[str] | None', default: 'None', description: 'A **value**.\n\n- One\n- Two\n\n```python\nx = 1\n```' }] },
            { kind: 'returns', value: [{ name: '', annotation: 'Item', default: null, description: '[Item][myogestic.Item]' }] },
            { kind: 'examples', value: '```pycon\n>>> Item()\n```' },
        ],
    } },
};

function html() {
    const tree = { type: 'root' as const, children: renderSymbol(api, { path: 'myogestic.Item', options: {} }, 'api/core', '/docs/api/core.md') };
    const processor = unified().use(remarkParse).use(remarkRehype, { allowDangerousHtml: true }).use(rehypeRaw);
    return toHtml(processor.runSync(tree));
}

describe('rendered API HTML', () => {
    it('renders real headings, escaped signatures, Markdown and structured tables', () => {
        const output = html();
        expect(output).toContain('<h3 id="myogestic.Item">Item</h3>');
        expect(output).toContain('<pre class="mg-signature"><code>Item(');
        expect(output).toContain('<strong>item</strong>');
        expect(output).toContain('<code>code</code>');
        expect(output).toContain('<div class="mg-params-scroll" tabindex="0" role="group" aria-label="Parameters for Item"><table class="mg-params">');
        expect(output).toContain('<td>\n<p>A <strong>value</strong>.</p>');
        expect(output).toContain('<li>One</li>');
        expect(output).toContain('class="language-python"');
        expect(output).toContain('class="language-pycon"');
    });

    it('resolves both docstring Markdown links and API links under the deployment base', () => {
        const output = html();
        expect(output).toContain('href="/MyoGestic/concepts/streams/"');
        expect(output).toContain('href="/MyoGestic/api/core/#myogestic.Item"');
    });
});
