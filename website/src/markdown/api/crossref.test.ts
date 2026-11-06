import { expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { remarkApiCrossref } from './crossref';

const inventory = { 'myogestic.ml.Pipeline': '/MyoGestic/api/ml/#myogestic.ml.Pipeline' };
function transform(source: string) {
    const processor = unified().use(remarkParse).use(remarkApiCrossref, { inventory });
    return JSON.stringify(processor.runSync(processor.parse(source), { path: '/docs/guide.md' }));
}

it('links explicit and collapsed references, preserving inline code', () => {
    const tree = transform('[`Pipeline`][myogestic.ml.Pipeline] and [myogestic.ml.Pipeline][]');
    expect(tree.match(/"type":"link"/g)).toHaveLength(2);
    expect(tree).toContain(inventory['myogestic.ml.Pipeline']);
    expect(tree).toContain('inlineCode');
});

it('throws on unknown API references with original page and line', () => {
    expect(() => transform('Intro\n\n[Thing][myogestic.nope.Thing]')).toThrow(/guide.md:3.*myogestic.nope.Thing/);
});

it('leaves code, images, regular links and ordinary reference definitions intact', () => {
    const tree = transform('`[Thing][myogestic.nope.Thing]`\n\n[site][home]\n\n[home]: https://example.com\n\n![alt](image.png)');
    expect(tree).toContain('linkReference');
    expect(tree).toContain('image');
});
