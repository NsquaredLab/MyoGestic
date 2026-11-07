import type { Root } from 'hast';
import type { Plugin } from 'unified';
import { toString } from 'hast-util-to-string';
import { visit } from 'unist-util-visit';

/** Python-Markdown's default toc.slugify (Unicode → ASCII, then punctuation removal). */
export function headingSlug(text: string): string {
    return text.normalize('NFKD').replace(/[^\x00-\x7F]/g, '').replace(/[^\w\s-]/g, '')
        .trim().toLowerCase().replace(/[-\s]+/g, '-');
}

export const rehypeHeadingIds: Plugin<[], Root> = () => (tree) => {
    const used = new Set<string>();
    // Reserve explicit IDs first, including API symbol anchors supplied by Task 3.
    visit(tree, 'element', (node) => {
        if (node.properties.id) used.add(String(node.properties.id));
    });
    visit(tree, 'element', (node) => {
        if (!/^h[1-6]$/.test(node.tagName) || node.properties.id) return;
        let id = headingSlug(toString(node));
        while (!id || used.has(id)) {
            const suffix = id.match(/^(.*)_([0-9]+)$/);
            id = suffix ? `${suffix[1]}_${Number(suffix[2]) + 1}` : `${id}_1`;
        }
        used.add(id);
        node.properties.id = id;
    });
};
