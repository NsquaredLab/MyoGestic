import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Root } from 'mdast';
import type { Plugin } from 'unified';
import { visit } from 'unist-util-visit';

const svgDirectory = fileURLToPath(new URL('../../../../docs/images/mermaid/', import.meta.url));

export const remarkMermaid: Plugin<[{ directory?: string }?], Root> = ({ directory = svgDirectory } = {}) => (tree, file) => {
    visit(tree, 'code', (node, index, parent) => {
        if (node.lang !== 'mermaid' || index === undefined || !parent) return;
        const hash = createHash('sha1').update(node.value).digest('hex').slice(0, 12);
        if (!existsSync(join(directory, `${hash}.svg`))) throw new Error(`${file.path ?? '<markdown>'}:${node.position?.start.line ?? 1}: missing Mermaid SVG ${hash}.svg; run node website/scripts/render-mermaid.mjs`);
        parent.children.splice(index, 1, {
            type: 'image', url: `/MyoGestic/images/mermaid/${hash}.svg`, alt: 'Diagram',
            data: { hProperties: { className: ['mg-diagram'] } },
        });
    });
};
