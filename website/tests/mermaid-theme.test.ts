import { readFileSync, readdirSync } from 'node:fs';
import { expect, it } from 'vitest';
import { mermaidTheme } from '../scripts/render-mermaid.mjs';

const css = readFileSync(new URL('../src/styles/tokens.css', import.meta.url), 'utf8');

it('uses the dark surface, text, border and line tokens for Mermaid', () => {
    const theme = mermaidTheme(css);
    const root = css.match(/:root \{([^}]+)\}/)![1];
    const dark = css.match(/\[data-theme='dark'\] \{([^}]+)\}/)![1];
    const tokens = Object.fromEntries([...`${root}\n${dark}`.matchAll(/(--mg-[\w-]+):\s*([^;]+);/g)]
        .map(([, name, value]) => [name, value.trim()]));
    expect(theme).toMatchObject({
        background: 'transparent', darkMode: true,
        primaryColor: tokens['--mg-raised'],
        primaryTextColor: tokens['--mg-text'], textColor: tokens['--mg-text'],
        primaryBorderColor: tokens['--mg-border'], clusterBorder: tokens['--mg-border'],
        clusterBkg: tokens['--mg-card'], edgeLabelBackground: tokens['--mg-card'],
        lineColor: tokens['--mg-idle'],
    });
    expect(mermaidTheme(css.replace(/--mg-raised:[^;]+;/, '--mg-raised: rebeccapurple;')).primaryColor)
        .toBe('rebeccapurple');
});

it('keeps text labels and token colours in all five committed diagrams', () => {
    const directory = new URL('../../docs/images/mermaid/', import.meta.url);
    const files = readdirSync(directory).filter(name => name.endsWith('.svg'));
    expect(files).toHaveLength(5);
    const theme = mermaidTheme(css);
    for (const file of files) {
        const svg = readFileSync(new URL(file, directory), 'utf8');
        expect(svg, file).toMatch(/<text[\s>]/);
        expect(svg, file).not.toContain('foreignObject');
        expect(svg, file).toContain(theme.primaryColor);
        expect(svg, file).toContain(theme.lineColor);
        expect(svg, file).toContain(theme.clusterBkg);
    }
});
