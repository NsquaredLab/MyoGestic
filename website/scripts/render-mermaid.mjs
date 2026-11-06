import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { visit } from 'unist-util-visit';

const docs = fileURLToPath(new URL('../../docs/', import.meta.url));
const output = join(docs, 'images/mermaid');
const diagrams = new Map();
const parser = unified().use(remarkParse);

async function scan(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
        if (entry.name === 'superpowers') continue;
        const path = join(directory, entry.name);
        if (entry.isDirectory()) await scan(path);
        else if (entry.name.endsWith('.md')) {
            visit(parser.parse(await readFile(path, 'utf8')), 'code', (node) => {
                if (node.lang !== 'mermaid') return;
                const hash = createHash('sha1').update(node.value).digest('hex').slice(0, 12);
                diagrams.set(hash, node.value);
            });
        }
    }
}

await scan(docs);
await mkdir(output, { recursive: true });
const temporary = await mkdtemp(join(tmpdir(), 'myogestic-mermaid-'));
let rendered = 0;
try {
    const config = join(temporary, 'config.json');
    await writeFile(config, JSON.stringify({
        fontFamily: 'system-ui, sans-serif',
        deterministicIds: true,
        deterministicIDSeed: 'myogestic',
        htmlLabels: false,
        flowchart: { htmlLabels: false },
    }));
    for (const [hash, source] of [...diagrams].sort(([a], [b]) => a.localeCompare(b))) {
        const svg = join(output, `${hash}.svg`);
        if (existsSync(svg)) continue;
        const input = join(temporary, `${hash}.mmd`);
        const staged = join(temporary, `${hash}.svg`);
        await writeFile(input, source);
        console.log(`Rendering ${hash}.svg`);
        const child = spawnSync('npx', ['-y', '@mermaid-js/mermaid-cli@11', '-t', 'dark', '-b', 'transparent', '-c', config, '-i', input, '-o', staged], { stdio: 'inherit' });
        if (child.error || child.status !== 0) throw child.error ?? new Error(`Mermaid renderer exited ${child.status} for ${hash}`);
        await rename(staged, svg);
        rendered++;
    }
    console.log(`${diagrams.size} Mermaid diagrams; rendered ${rendered}, kept ${diagrams.size - rendered} existing SVGs.`);
} finally {
    await rm(temporary, { recursive: true, force: true });
}
