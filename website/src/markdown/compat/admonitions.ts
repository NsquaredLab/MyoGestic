import type { Blockquote, Paragraph, Root } from 'mdast';
import type { Parser, Plugin } from 'unified';
import { visit } from 'unist-util-visit';

interface Callout { type: string; title: string; marker: string }
const marker = /^ {0,3}(!!!|\?\?\?\+?)\s+([\w-]+)(?:\s+(?:"(.*)"|'(.*)'))?\s*$/;

/** Quote the indented body before Markdown parsing, keeping source line numbers intact. */
function quoteCallouts(lines: string[], firstLine: number, callouts: Map<number, Callout>): string[] {
    const result: string[] = [];
    let fence: { char: string; length: number } | undefined;
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const delimiter = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
        if (fence) {
            result.push(line);
            if (delimiter && delimiter[1][0] === fence.char && delimiter[1].length >= fence.length && !delimiter[2].trim()) fence = undefined;
            continue;
        }
        if (delimiter) {
            fence = { char: delimiter[1][0], length: delimiter[1].length };
            result.push(line);
            continue;
        }
        const match = line.match(marker);
        if (!match) { result.push(line); continue; }
        const [, kind, type, doubleTitle, singleTitle] = match;
        callouts.set(firstLine + i, { marker: kind, type, title: doubleTitle ?? singleTitle ?? type[0].toUpperCase() + type.slice(1) });
        // A heading makes the title a distinct block even when the body starts on the next line.
        result.push('> # callout');
        let end = i + 1;
        while (end < lines.length && (!lines[end].trim() || /^(?: {4}|\t)/.test(lines[end]))) end++;
        // Do not quote the blank lines that separate the callout from the next block.
        while (end > i + 1 && !lines[end - 1].trim()) end--;
        const body = lines.slice(i + 1, end).map((bodyLine) => bodyLine.replace(/^(?: {4}|\t)/, ''));
        result.push(...quoteCallouts(body, firstLine + i + 1, callouts).map((bodyLine) => '> ' + bodyLine));
        i = end - 1;
    }
    return result;
}

/** Parse callouts as real Markdown nodes so links, fences and later plugins still work. */
export const remarkAdmonitions: Plugin<[], Root> = function () {
    const parse = this.parser as Parser<Root>;
    this.parser = (source, file) => {
        const callouts = new Map<number, Callout>();
        const tree = parse(quoteCallouts(source.split(/\r?\n/), 1, callouts).join('\n'), file);
        visit(tree, 'blockquote', (node: Blockquote) => {
            const titleNode = node.children[0];
            const callout = callouts.get(titleNode?.position?.start.line ?? -1);
            if (!callout || titleNode.type !== 'heading') return;
            const collapsible = callout.marker !== '!!!';
            node.data = {
                hName: collapsible ? 'details' : 'aside',
                hProperties: { className: ['mg-callout', `mg-callout--${callout.type}`], ...(callout.marker === '???+' ? { open: true } : {}) },
            };
            const title = parse(callout.title, file).children[0] as Paragraph | undefined;
            node.children.splice(0, 1, ...(callout.title ? [{
                type: 'paragraph' as const,
                children: title?.children ?? [],
                data: { hName: collapsible ? 'summary' : 'p', hProperties: { className: ['mg-callout__title'] } },
            }] : []));
        });
        return tree;
    };
};
