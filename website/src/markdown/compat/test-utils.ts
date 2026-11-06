import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkRehype from 'remark-rehype';
import rehypeStringify from 'rehype-stringify';
import type { PluggableList } from 'unified';

export async function render(markdown: string, remark: PluggableList = [], rehype: PluggableList = [], path = '/docs/example.md') {
    return String(await unified().use(remarkParse).use(remark).use(remarkRehype, { allowDangerousHtml: true })
        .use(rehype).use(rehypeStringify, { allowDangerousHtml: true }).process({ value: markdown, path }));
}
