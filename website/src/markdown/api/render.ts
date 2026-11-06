import { readFileSync } from 'node:fs';
import { posix } from 'node:path';
import type { Heading, Root, RootContent } from 'mdast';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { visit } from 'unist-util-visit';
import { remarkApiCrossref } from './crossref';

export interface Param { name: string; annotation: string; description: string; default: string | null }
export interface Section { kind: string; title?: string; value: string | Param[] }
export interface Symbol {
    kind: 'module' | 'class' | 'function' | 'attribute'; path: string; name: string;
    signature: string | null; labels: string[]; bases: string[]; docstring: Section[]; members: string[];
}
export interface Directive { path: string; options: Record<string, unknown> }
export interface ApiData { pages: Record<string, Directive[]>; symbols: Record<string, Symbol>; inventory: Record<string, string> }
let cached: ApiData | undefined;
export function loadApiData(): ApiData {
    if (!cached) {
        try {
            cached = JSON.parse(readFileSync(new URL('../../generated/api.json', import.meta.url), 'utf8'));
        } catch (error) {
            throw new Error('Generate API data first: uv run --extra docs python website/scripts/gen_api.py', { cause: error });
        }
    }
    return cached!;
}

function escape(text: string) {
    return text.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
}
function heading(text: string, depth: number, id?: string): RootContent {
    return { type: 'heading', depth: Math.min(6, depth) as Heading['depth'], children: [{ type: 'text', value: text }], ...(id ? { data: { hProperties: { id } } } : {}) };
}

/** Build ordinary Markdown nodes so Astro renders docstring Markdown normally. */
export function renderSymbol(data: ApiData, directive: Directive, page: string, filename: string, depth = 3, seen = new Set<string>()): RootContent[] {
    const symbol = data.symbols[directive.path];
    if (!symbol) throw new Error(`${filename}: unknown API directive ${directive.path}`);
    if (seen.has(symbol.path)) return [];
    seen.add(symbol.path);
    const output: RootContent[] = [];
    const options = directive.options;
    if (options.show_root_heading !== false) {
        output.push(heading(options.show_root_full_path ? symbol.path : symbol.name, depth, symbol.path));
    } else {
        output.push({ type: 'html', value: `<span id="${escape(symbol.path)}"></span>` });
    }
    if (symbol.signature) output.push({ type: 'html', value: `<pre class="mg-signature"><code>${escape(symbol.signature)}</code></pre>` });
    if (symbol.bases.length) output.push({ type: 'paragraph', children: [{ type: 'text', value: 'Bases: ' }, { type: 'inlineCode', value: symbol.bases.join(', ') }] });
    const processor = unified().use(remarkParse).use(remarkApiCrossref, { inventory: data.inventory });
    function markdown(value: string): RootContent[] {
        const tree = processor.runSync(processor.parse(value), { path: filename, value }) as Root;
        visit(tree, (node) => {
            if ('url' in node && typeof node.url === 'string' && !/^(?:[a-z][\w+.-]*:|\/\/|#|\?|\/MyoGestic\/)/i.test(node.url)) {
                const [, pathname, suffix] = node.url.match(/^([^?#]*)(.*)$/)!;
                let target = pathname.startsWith('/') ? pathname.slice(1) : posix.join(posix.dirname(page), pathname);
                target = target.replace(/(?:^|\/)(?:index|README)\.md$/, '').replace(/\.md$/, '/');
                node.url = '/MyoGestic/' + target + suffix;
            }
        });
        return tree.children;
    }
    for (const section of symbol.docstring) {
        if (section.kind !== 'text') output.push(heading(section.title ?? section.kind[0].toUpperCase() + section.kind.slice(1), depth + 1));
        if (typeof section.value === 'string') {
            output.push(...markdown(section.value));
        } else {
            // Raw table boundaries allow Markdown paragraphs, lists and code in cells.
            output.push({ type: 'html', value: '<table class="mg-params"><thead><tr><th scope="col">Name</th><th scope="col">Type</th><th scope="col">Description</th><th scope="col">Default</th></tr></thead><tbody>' });
            for (const param of section.value) {
                output.push({ type: 'html', value: `<tr><td><code>${escape(param.name)}</code></td><td><code>${escape(param.annotation)}</code></td><td>` });
                output.push(...markdown(param.description));
                output.push({ type: 'html', value: `</td><td>${param.default === null ? '' : `<code>${escape(param.default)}</code>`}</td></tr>` });
            }
            output.push({ type: 'html', value: '</tbody></table>' });
        }
    }
    const chosen = options.members;
    if (chosen !== false) for (const member of symbol.members) {
        if (Array.isArray(chosen) && !chosen.includes(member.slice(symbol.path.length + 1))) continue;
        output.push(...renderSymbol(data, { path: member, options: {} }, page, filename, depth + 1, seen));
    }
    return output;
}
