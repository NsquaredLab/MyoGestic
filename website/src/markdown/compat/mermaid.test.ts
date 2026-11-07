import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { remarkMermaid } from './mermaid';
import { render } from './test-utils';

const dirs: string[] = [];
afterEach(() => { for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true }); });

describe('static Mermaid diagrams', () => {
    const body = 'flowchart LR\n    A[Stream] --> B[Pipeline]';
    const hash = createHash('sha1').update(body).digest('hex').slice(0, 12);

    it('links a fence to its committed SVG under the site base', async () => {
        const directory = mkdtempSync(join(tmpdir(), 'myogestic-mermaid-test-'));
        dirs.push(directory);
        writeFileSync(join(directory, `${hash}.svg`), '<svg xmlns="http://www.w3.org/2000/svg"/>');
        const html = await render(`\`\`\`mermaid\n${body}\n\`\`\``, [[remarkMermaid, { directory }]]);
        expect(html).toBe(`<img src="/MyoGestic/images/mermaid/${hash}.svg" alt="Diagram" class="mg-diagram">`);
    });

    it('fails with the source page and hash if an SVG has not been rendered', async () => {
        await expect(render(`\`\`\`mermaid\n${body}\n\`\`\``, [[remarkMermaid, { directory: '/missing' }]]))
            .rejects.toThrow(`/docs/example.md:1: missing Mermaid SVG ${hash}.svg`);
    });
});
