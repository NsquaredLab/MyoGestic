import { readFile, readdir, stat } from 'node:fs/promises';
import { join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'parse5';

const dist = resolve(process.argv[2] ?? fileURLToPath(new URL('../dist/', import.meta.url)));
const origin = 'https://nsquaredlab.github.io';
const base = '/MyoGestic/';
const offenders = new Set();
let pages = 0;
let checked = 0;

async function checkPage(path) {
    pages++;
    const page = relative(dist, path).split(sep).join('/');
    const document = parse(await readFile(path, 'utf8'));
    const links = [];
    function walk(node) {
        for (const attr of node.attrs ?? []) {
            if (['href', 'src'].includes(attr.name)) links.push(attr);
        }
        for (const child of node.childNodes ?? []) walk(child);
        if (node.content) walk(node.content);
    }
    walk(document);
    for (const { name, value } of links) {
        if (!value || value.startsWith('#') || value.startsWith('?')) continue;
        let url;
        try {
            url = new URL(value, `${origin}${base}${page}`);
        } catch {
            offenders.add(`${page}: ${name}="${value}" (invalid URL)`);
            continue;
        }
        if (url.origin !== origin) continue;
        checked++;
        // Same-origin absolute URLs are allowed; relative and root-only paths are not.
        const absolute = /^(?:https?:)?\/\//.test(value);
        if (!url.pathname.startsWith(base) || (!absolute && !value.startsWith(base))) {
            offenders.add(`${page}: ${name}="${value}" (must start with ${base})`);
            continue;
        }
        let target;
        try {
            target = resolve(dist, decodeURIComponent(url.pathname.slice(base.length)) || '.');
        } catch {
            offenders.add(`${page}: ${name}="${value}" (invalid URL encoding)`);
            continue;
        }
        if (target !== dist && !target.startsWith(dist + sep)) {
            offenders.add(`${page}: ${name}="${value}" (leaves dist/)`);
            continue;
        }
        let info = await stat(target).catch(() => null);
        if (info?.isDirectory()) {
            target = join(target, 'index.html');
            info = await stat(target).catch(() => null);
        }
        if (!info?.isFile()) offenders.add(`${page}: ${name}="${value}" (missing ${relative(dist, target)})`);
    }
}

async function walkDist(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
        const path = join(directory, entry.name);
        if (entry.isDirectory()) await walkDist(path);
        else if (entry.name.endsWith('.html')) await checkPage(path);
    }
}
await walkDist(dist);
if (pages === 0) throw new Error(`No built HTML pages found in ${dist}`);
if (offenders.size) {
    console.error(`Found ${offenders.size} internal link problems:\n${[...offenders].sort().join('\n')}`);
    process.exitCode = 1;
} else {
    console.log(`Checked ${checked} internal links across ${pages} HTML pages: no broken links.`);
}
