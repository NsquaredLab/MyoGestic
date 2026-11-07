import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

it('checks the saved URI anchors for all legacy aliases and fails when a target disappears', () => {
    const directory = mkdtempSync(join(tmpdir(), 'myogestic-api-'));
    const pages = new Map<string, Set<string>>();
    const lines = readFileSync(new URL('../../../tests/legacy-symbols.txt', import.meta.url), 'utf8').trim().split('\n');
    for (const line of lines) {
        const [name, , uri] = line.split('\t');
        const [page, fragment] = uri.split('#');
        const anchors = pages.get(page) ?? new Set<string>();
        anchors.add(fragment.replaceAll('$', name));
        pages.set(page, anchors);
    }
    try {
        for (const [page, anchors] of pages) {
            mkdirSync(join(directory, page), { recursive: true });
            writeFileSync(join(directory, page, 'index.html'), [...anchors].map((id) => `<h3 id="${id}">Symbol</h3>`).join('\n'));
        }
        const generated = join(directory, 'api.json');
        writeFileSync(generated, JSON.stringify({ inventory: {} }));
        const check = () => spawnSync(process.execPath, [fileURLToPath(new URL('../../../scripts/check-api.mjs', import.meta.url)), directory, generated], { encoding: 'utf8' });
        const success = check();
        expect(success.status).toBe(0);
        expect(success.stdout).toContain('808/808');
        expect(success.stdout).toContain('no exemptions');
        writeFileSync(generated, JSON.stringify({ inventory: { 'myogestic.NewAPI': '/MyoGestic/api/core/#myogestic.NewAPI' } }));
        const stale = check();
        expect(stale.status).toBe(1);
        expect(stale.stderr).toContain('myogestic.NewAPI');
        writeFileSync(generated, JSON.stringify({ inventory: {} }));
        const page = join(directory, 'api/core/index.html');
        writeFileSync(page, readFileSync(page, 'utf8').replace('id="myogestic.App"', 'id="missing"'));
        const failure = check();
        expect(failure.status).toBe(1);
        expect(failure.stderr).toContain('missing #myogestic.App in api/core/');
    } finally {
        rmSync(directory, { recursive: true, force: true });
    }
});
