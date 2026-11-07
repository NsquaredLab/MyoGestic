import { dirname, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { AstroUserConfig } from 'astro';
import type { Root } from 'mdast';
import type { Plugin } from 'unified';
import { visit } from 'unist-util-visit';
import { compatRemark, compatRehype } from './compat';
import { apiRemark } from './api';

const docsRoot = fileURLToPath(new URL('../../../docs/', import.meta.url));
const base = '/MyoGestic/';

/** Keep source-relative docs links and public assets valid under the site base. */
export const remarkContentLinks: Plugin<[], Root> = () => (tree, file) => {
    if (!file.path) return;
    const page = relative(docsRoot, file.path);
    if (page.startsWith('..')) return;
    visit(tree, (node) => {
        if (!('url' in node) || typeof node.url !== 'string') return;
        const url = node.url;
        if (!url || /^(?:[a-z][\w+.-]*:|\/\/|#|\?)/i.test(url) || url.startsWith(base)) return;
        const [, pathname, suffix] = url.match(/^([^?#]*)(.*)$/)!;
        let target = pathname.startsWith('/')
            ? pathname.slice(1)
            : relative(docsRoot, resolve(dirname(file.path), pathname)).split(sep).join('/');
        if (target.startsWith('../')) {
            throw new Error(`${file.path}: documentation link leaves docs/: ${url}`);
        }
        if (target.endsWith('.md')) {
            target = target.replace(/(?:^|\/)(?:index|README)\.md$/, '').replace(/\.md$/, '');
            if (target) target += '/';
        } else if (!target || pathname.endsWith('/')) {
            target = target.replace(/\/$/, '') + (target ? '/' : '');
        }
        node.url = base + target + suffix;
    });
};

type MarkdownConfig = NonNullable<AstroUserConfig['markdown']>;
export const remarkPlugins = [remarkContentLinks, ...compatRemark, ...apiRemark] as NonNullable<MarkdownConfig['remarkPlugins']>;
export const rehypePlugins = [...compatRehype] as NonNullable<MarkdownConfig['rehypePlugins']>;
