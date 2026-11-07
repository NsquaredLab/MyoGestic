import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { parse, serialize } from 'parse5';
import { ASK_SEARCH } from '../src/context7-ask.mjs';

const docs = new URL('../../docs/', import.meta.url);
const publicDir = new URL('../public/', import.meta.url);
await mkdir(publicDir, { recursive: true });
for (const name of ['images', 'playground']) {
    const destination = new URL(name, publicDir);
    await rm(destination, { recursive: true, force: true });
    await cp(new URL(name, docs), destination, { recursive: true });
}
// The published llms.txt gains the Context7 Ask search section after the title and summary.
const llms = await readFile(new URL('llms.txt', docs), 'utf8');
const summaryEnd = llms.indexOf('\n\n', llms.indexOf('\n>'));
if (!llms.startsWith('# ') || summaryEnd < 0) throw new Error('docs/llms.txt must open with a title and a > summary');
await writeFile(new URL('llms.txt', publicDir), `${llms.slice(0, summaryEnd)}\n\n## Search\n\n${ASK_SEARCH}${llms.slice(summaryEnd)}`);

// The Playground stays a static app. Normalize only its published HTML URLs.
async function normalizeHtml(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
        const path = new URL(entry.name, directory);
        if (entry.isDirectory()) {
            await normalizeHtml(new URL(`${entry.name}/`, directory));
        } else if (entry.name.endsWith('.html')) {
            const relative = fileURLToPath(path).slice(fileURLToPath(publicDir).length);
            const current = new URL(`/MyoGestic/${relative}`, 'https://nsquaredlab.github.io');
            const document = parse(await readFile(path, 'utf8'));
            function walk(node) {
                for (const attr of node.attrs ?? []) {
                    if (!['href', 'src'].includes(attr.name) || !attr.value || /^(?:[a-z][\w+.-]*:|\/\/|#|\?)/i.test(attr.value)) continue;
                    const target = new URL(attr.value, current);
                    attr.value = target.pathname + target.search + target.hash;
                }
                for (const child of node.childNodes ?? []) walk(child);
                if (node.content) walk(node.content);
            }
            walk(document);
            await writeFile(path, serialize(document));
        }
    }
}
await normalizeHtml(new URL('playground/', publicDir));
console.log('Synced docs/images, docs/playground and docs/llms.txt to public/.');
