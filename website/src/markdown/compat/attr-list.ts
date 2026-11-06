import type { Root } from 'mdast';
import type { Plugin } from 'unified';
import { visit } from 'unist-util-visit';

function attributes(source: string, image: boolean) {
    const properties: Record<string, string> = {};
    for (const match of source.matchAll(/(?:^|\s)(#[\w.:-]+|[\w-]+=(?:"[^"]*"|'[^']*'|[^\s]+))/g)) {
        if (match[1].startsWith('#')) { properties.id = match[1].slice(1); continue; }
        const equals = match[1].indexOf('=');
        const key = match[1].slice(0, equals);
        if (image && ['loading', 'decoding', 'width', 'height', 'title', 'align'].includes(key)) properties[key] = match[1].slice(equals + 1).replace(/^(["'])(.*)\1$/, '$2');
    }
    return properties;
}

export const remarkAttrList: Plugin<[], Root> = () => (tree) => {
    visit(tree, (parent) => {
        if (!('children' in parent)) return;
        const children = parent.children;
        for (let i = 1; i < children.length; i++) {
            const node = children[i];
            const previous = children[i - 1];
            if (node.type !== 'text' || !['image', 'link', 'imageReference', 'linkReference', 'html'].includes(previous.type)) continue;
            const match = node.value.match(/^\s*\{\s*([^}]+)\}/);
            if (!match || !/(?:^|\s)[.#\w]/.test(match[1])) continue;
            if (previous.type === 'html' && !previous.value.startsWith('<svg class="mg-icon"')) continue;
            if (previous.type !== 'html') previous.data = {
                ...previous.data,
                hProperties: { ...previous.data?.hProperties, ...attributes(match[1], previous.type === 'image') },
            };
            node.value = node.value.slice(match[0].length);
        }
        if (parent.type === 'heading') {
            const last = children.at(-1);
            if (last?.type !== 'text') return;
            const match = last.value.match(/\s*\{\s*([^}]*#[\w.:-]+[^}]*)\}\s*$/);
            if (!match) return;
            parent.data = { ...parent.data, hProperties: { ...parent.data?.hProperties, ...attributes(match[1], false) } };
            last.value = last.value.slice(0, match.index).trimEnd();
        }
    });
};
