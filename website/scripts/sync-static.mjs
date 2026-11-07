import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { parse, serialize } from 'parse5';

const docs = new URL('../../docs/', import.meta.url);
const publicDir = new URL('../public/', import.meta.url);
await mkdir(publicDir, { recursive: true });
for (const name of ['images', 'playground']) {
    const destination = new URL(name, publicDir);
    await rm(destination, { recursive: true, force: true });
    await cp(new URL(name, docs), destination, { recursive: true });
}
await cp(new URL('llms.txt', docs), new URL('llms.txt', publicDir));

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
