import type { Parent, Root } from 'mdast';
import type { Plugin } from 'unified';
import { parse } from 'yaml';
import { visit } from 'unist-util-visit';
import { loadApiData, renderSymbol, type ApiData } from './render';

/** Replace mkdocstrings paragraphs and their YAML options with API nodes. */
export const remarkApiDirective: Plugin<[{ data?: ApiData }?], Root> = (options = {}) => {
    const data = options.data ?? loadApiData();
    return (tree, file) => {
        const filename = file.path || '<markdown>';
        const parsedSource = String(file.data.mgParsedSource ?? file.value);
        const page = filename.replace(/\\/g, '/').match(/(?:^|\/docs\/)(api\/[^/]+)\.md$/)?.[1] ?? 'api/index';
        const seen = new Set<string>();
        visit(tree, 'paragraph', (node, index, parent) => {
            if (!parent || index === undefined) return;
            const raw = parsedSource.slice(node.position?.start.offset, node.position?.end.offset);
            const source = raw || node.children.map((child) => child.type === 'text' ? child.value : '').join('');
            if (!/^::: [\w.]+(?:\s|$)/.test(source)) return;
            const lines = source.split('\n');
            const rendered: Root['children'] = [];
            let line = 0;
            while (line < lines.length) {
                const match = /^::: ([\w.]+)\s*$/.exec(lines[line]);
                if (!match) throw new Error(`${filename}:${(node.position?.start.line ?? 1) + line}: invalid API directive configuration`);
                const path = match[1];
                if (!data.symbols[path]) throw new Error(`${filename}:${(node.position?.start.line ?? 1) + line}: unknown API directive ${path}`);
                line++;
                const block: string[] = [];
                while (line < lines.length && !lines[line].startsWith('::: ')) block.push(lines[line++]);
                const content = block.join('\n').replace(/^ {4}/gm, '');
                const config = parse(content) ?? {};
                if (config.options !== undefined && (config.options === null || typeof config.options !== 'object' || Array.isArray(config.options))) {
                    throw new Error(`${filename}: options for ${path} must be a mapping`);
                }
                rendered.push(...renderSymbol(data, { path, options: config.options ?? {} }, page, filename, 3, seen));
            }
            (parent as Parent).children.splice(index, 1, ...rendered);
            return index + rendered.length;
        });
    };
};
