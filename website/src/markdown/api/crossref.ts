import type { Root } from 'mdast';
import type { Plugin } from 'unified';
import { visit } from 'unist-util-visit';
import { loadApiData } from './render';

/** Give otherwise undefined Python references to remark's normal inline parser. */
export const remarkApiCrossref: Plugin<[{ inventory?: Record<string, string> }?], Root> = function (options = {}) {
    const inventory = options.inventory ?? loadApiData().inventory;
    const paths = new Map(Object.entries(inventory).map(([path, url]) => [path.toLowerCase(), { path, url }]));
    const parser = this.parser;
    if (!parser) throw new Error('API cross-references require the Markdown parser');
    this.parser = (source, file) => {
        const references = new Set([...source.matchAll(/\[(myogestic(?:\.[A-Za-z_]\w*)+)\]/g)].map((match) => match[1]));
        // Appended definitions keep all original line/column offsets intact.
        const definitions = [...references].map((path) => `[${path}]: ${paths.get(path.toLowerCase())?.url ?? '#unknown-api-reference'}`).join('\n');
        const tree = parser(`${source}\n\n${definitions}`, file) as Root;
        tree.children = tree.children.filter((node) => !(node.type === 'definition' && (node.position?.start.offset ?? 0) > source.length));
        return tree;
    };
    return (tree, file) => {
        visit(tree, 'linkReference', (node, index, parent) => {
            if (!node.identifier.startsWith('myogestic.')) return;
            const target = paths.get(node.identifier.toLowerCase());
            if (!target) {
                throw new Error(`${file.path || '<markdown>'}:${node.position?.start.line ?? 1}: unknown API reference ${node.label ?? node.identifier}`);
            }
            if (parent && index !== undefined) {
                parent.children[index] = { type: 'link', url: target.url, children: node.children, position: node.position };
            }
        });
    };
};
