import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, sep } from 'node:path';
import { parse, type DefaultTreeAdapterMap } from 'parse5';
import { expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { visit } from 'unist-util-visit';

const dist = resolve(fileURLToPath(new URL('../dist/', import.meta.url)));
const origin = 'https://nsquaredlab.github.io';
const base = '/MyoGestic/';
const source = readFileSync(new URL('../../docs/llms.txt', import.meta.url), 'utf8');
const links = new Set<string>();
visit(unified().use(remarkParse).parse(source), 'link', (node) => {
    const url = new URL(node.url, origin + base);
    if (url.origin === origin && url.pathname.startsWith(base) && url.hash) links.add(node.url);
});

it('finds at least one legacy anchor to validate', () => { expect(links.size).toBeGreaterThan(0); });

for (const link of links) {
    it(`keeps the llms.txt deep link ${link}`, () => {
        const url = new URL(link, origin + base);
        const path = resolve(dist, decodeURIComponent(url.pathname.slice(base.length)), 'index.html');
        expect(path.startsWith(dist + sep)).toBe(true);
        const ids = new Set<string>();
        function walk(node: DefaultTreeAdapterMap['node']) {
            for (const attr of ('attrs' in node ? node.attrs : []) ?? []) if (attr.name === 'id') ids.add(attr.value);
            for (const child of ('childNodes' in node ? node.childNodes : []) ?? []) walk(child);
            if ('content' in node) walk(node.content);
        }
        walk(parse(readFileSync(path, 'utf8')));
        expect(ids, `Missing ${url.hash} in ${path}`).toContain(decodeURIComponent(url.hash.slice(1)));
    });
}
