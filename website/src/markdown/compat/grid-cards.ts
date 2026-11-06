import type { Blockquote, Root, RootContent } from 'mdast';
import type { Parser, Plugin } from 'unified';
import { visit } from 'unist-util-visit';

const opener = /^<div\s+class=["']([^"']+)["']\s+markdown(?:=["']?1["']?)?\s*>\s*/;

/** Parse HTML-with-Markdown before transforms, including the base-aware link pass. */
export const remarkGridCards: Plugin<[], Root> = function () {
    const parse = this.parser as Parser<Root>;
    this.parser = (source, file) => {
        const tree = parse(source, file);
        visit(tree, (parent) => {
            if (!('children' in parent)) return;
            const children = parent.children as RootContent[];
            for (let i = 0; i < children.length; i++) {
                const opening = children[i];
                if (opening.type !== 'html') continue;
                const match = opening.value.match(opener);
                if (!match) continue;
                let body: RootContent[];
                let count = 1;
                const remainder = opening.value.slice(match[0].length);
                if (/<\/div>\s*$/.test(remainder)) {
                    body = parse(remainder.replace(/<\/div>\s*$/, ''), file).children;
                } else {
                    let end = i + 1;
                    while (end < children.length && !(children[end].type === 'html' && /^<\/div>\s*$/.test((children[end] as { value: string }).value))) end++;
                    if (end === children.length) throw new Error(`${file.path ?? '<markdown>'}:${opening.position?.start.line}: unclosed Markdown div`);
                    body = [...(remainder.trim() ? parse(remainder, file).children : []), ...children.slice(i + 1, end)];
                    count = end - i + 1;
                }
                const classes = match[1].split(/\s+/);
                const cards = classes.includes('grid') && classes.includes('cards');
                if (cards) {
                    body = body.flatMap((node) => node.type === 'list' ? node.children.map((item): Blockquote => ({
                        type: 'blockquote', children: item.children,
                        data: { hName: 'div', hProperties: { className: ['mg-card'] } },
                    })) : [node]);
                }
                children.splice(i, count, {
                    type: 'blockquote', children: body as Blockquote['children'],
                    data: { hName: 'div', hProperties: { className: cards ? ['mg-cards'] : classes } },
                    position: opening.position,
                });
            }
        });
        return tree;
    };
};
