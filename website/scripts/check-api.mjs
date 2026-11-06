import { readFile } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'parse5';

const dist = resolve(process.argv[2] ?? fileURLToPath(new URL('../dist/', import.meta.url)));
const legacy = await readFile(new URL('../tests/legacy-symbols.txt', import.meta.url), 'utf8');
const generated = JSON.parse(await readFile(process.argv[3] ?? new URL('../src/generated/api.json', import.meta.url), 'utf8'));
const pages = new Map();

async function checkTarget(name, uri) {
    const [page, anchor] = uri.split('#');
    const path = resolve(dist, page, 'index.html');
    if (!path.startsWith(dist + sep)) throw new Error(`Inventory URI leaves dist: ${uri}`);
    if (!pages.has(path)) {
        const html = await readFile(path, 'utf8').catch(() => null);
        const ids = new Set();
        function walk(node) {
            for (const attr of node.attrs ?? []) if (attr.name === 'id') ids.add(attr.value);
            for (const child of node.childNodes ?? []) walk(child);
        }
        if (html !== null) walk(parse(html));
        pages.set(path, { html, ids });
    }
    const result = pages.get(path);
    const id = decodeURIComponent((anchor || name).replaceAll('$', name));
    if (result.html === null) return `${name}: missing ${page}`;
    if (!result.ids.has(id)) return `${name}: missing #${id} in ${page}`;
}

const missing = [];
let checked = 0;
for (const line of legacy.trim().split(/\r?\n/)) {
    const [name, , uri] = line.split('\t');
    const problem = await checkTarget(name, uri);
    if (problem) missing.push(problem);
    checked++;
}
if (missing.length) {
    console.error(`Resolved ${checked - missing.length}/${checked} legacy API symbols; ${missing.length} missing:\n${missing.join('\n')}`);
    process.exitCode = 1;
} else {
    console.log(`Resolved ${checked}/${checked} legacy API symbols across ${pages.size} pages; no exemptions.`);
}

// The frozen inventory cannot cover new APIs. Check every generated destination
// too, so stale content-layer caches and filtered-out members fail this gate.
const missingGenerated = [];
const inventory = Object.entries(generated.inventory);
for (const [name, href] of inventory) {
    if (!href.startsWith('/MyoGestic/')) throw new Error(`${name}: invalid API URL ${href}`);
    const problem = await checkTarget(name, href.slice('/MyoGestic/'.length));
    if (problem) missingGenerated.push(problem);
}
if (missingGenerated.length) {
    console.error(`Resolved ${inventory.length - missingGenerated.length}/${inventory.length} generated API references; ${missingGenerated.length} missing:\n${missingGenerated.join('\n')}`);
    process.exitCode = 1;
} else {
    console.log(`Resolved ${inventory.length}/${inventory.length} generated API references.`);
}
