import { readFile, stat } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = resolve(process.argv[2] ?? fileURLToPath(new URL('../dist/', import.meta.url)));
const baseline = process.argv[3] ?? new URL('../tests/legacy-urls.txt', import.meta.url);
const urls = (await readFile(baseline, 'utf8')).split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith('#'));
const missing = [];
for (const url of urls) {
    const path = join(dist, url.replace(/^\/+|\/+$/g, ''), 'index.html');
    if (!(await stat(path).catch(() => null))?.isFile()) missing.push(url);
}
if (missing.length) {
    console.error(`Missing ${missing.length} legacy URLs:\n${missing.join('\n')}`);
    process.exitCode = 1;
} else {
    console.log(`All ${urls.length} legacy URLs resolve in dist/.`);
}
