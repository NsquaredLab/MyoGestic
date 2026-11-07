import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
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

/** Resolve static SVG colours from the same tokens as the app's dark theme. */
export function mermaidTheme(css) {
    const tokens = {};
    for (const selector of [':root', "[data-theme='dark']"]) {
        const body = css.slice(css.indexOf(selector + ' {')).split('{')[1]?.split('}')[0];
        if (!body) throw new Error(`Missing token selector ${selector}`);
        for (const [, name, value] of body.matchAll(/(--mg-[\w-]+)\s*:\s*([^;]+);/g)) tokens[name] = value.trim();
    }
    function token(name) {
        if (!tokens[name]) throw new Error(`Missing Mermaid colour token ${name}`);
        return tokens[name];
    }
    return {
        darkMode: true,
        background: 'transparent',
        primaryColor: token('--mg-raised'),
        primaryTextColor: token('--mg-text'),
        primaryBorderColor: token('--mg-border'),
        secondaryColor: token('--mg-card'),
        secondaryBorderColor: token('--mg-border'),
        clusterBkg: token('--mg-card'),
        clusterBorder: token('--mg-border'),
        lineColor: token('--mg-idle'),
        textColor: token('--mg-text'),
        edgeLabelBackground: token('--mg-card'),
    };
}

async function main() {
    await scan(docs);
    await mkdir(output, { recursive: true });
    const temporary = await mkdtemp(join(tmpdir(), 'myogestic-mermaid-'));
    let rendered = 0;
    try {
        const config = join(temporary, 'config.json');
        const css = await readFile(new URL('../src/styles/tokens.css', import.meta.url), 'utf8');
        await writeFile(config, JSON.stringify({
            theme: 'base',
            themeVariables: mermaidTheme(css),
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
            const child = spawnSync('npx', ['-y', '@mermaid-js/mermaid-cli@11', '-b', 'transparent', '-c', config, '-i', input, '-o', staged], { stdio: 'inherit' });
            if (child.error || child.status !== 0) throw child.error ?? new Error(`Mermaid renderer exited ${child.status} for ${hash}`);
            await rename(staged, svg);
            rendered++;
        }
        console.log(`${diagrams.size} Mermaid diagrams; rendered ${rendered}, kept ${diagrams.size - rendered} existing SVGs.`);
    } finally {
        await rm(temporary, { recursive: true, force: true });
    }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
