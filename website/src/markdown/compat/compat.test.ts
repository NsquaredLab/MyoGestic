import { createMarkdownProcessor } from '@astrojs/markdown-remark';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { remarkContentLinks } from '../plugins';
import { compatRemark, compatRehype } from '../compat';

const remarkPlugins = [remarkContentLinks, ...compatRemark];
const rehypePlugins = compatRehype;

describe('the Astro Markdown pipeline', () => {
    it('renders compatibility syntax before Astro collects headings, links and images', async () => {
        const processor = await createMarkdownProcessor({ remarkPlugins, rehypePlugins, syntaxHighlight: false, smartypants: false });
        const { code, metadata } = await processor.render('## `Pipeline(app)` adds\n\n## Usage\n\n## Usage\n\n!!! info "No amplifier?"\n    [Get started](getting-started.md).\n\n<div class="grid cards" markdown>\n\n- :material-keyboard:{ .lg .middle } **Keyboard**\n\n  ![Keys](images/widgets/FilterControl.png){ .skip-lightbox loading=lazy }\n\n  [API](api/keyboard.md)\n\n</div>\n\n<!--docs:run-->\n```python\nx = 1\n```', {
            fileURL: new URL('../../../../docs/example.md', import.meta.url),
        });
        expect(metadata.headings.map(({ slug }) => slug)).toEqual(['pipelineapp-adds', 'usage', 'usage_1']);
        expect(code).toContain('class="mg-callout mg-callout--info"');
        expect(code).toContain('href="/MyoGestic/getting-started/"');
        expect(code).toContain('class="mg-cards"');
        expect(code).toContain('class="mg-card"');
        expect(code).toContain('class="mg-icon"');
        expect(code).toContain('src="/MyoGestic/images/widgets/FilterControl.png"');
        expect(code).toContain('loading="lazy"');
        expect(code).toContain('<!--docs:run-->');
        expect(code).not.toContain('.skip-lightbox');
    });

    it('leaves API cross-references and directives for Task 3', async () => {
        const processor = await createMarkdownProcessor({ remarkPlugins, rehypePlugins, syntaxHighlight: false });
        const { code } = await processor.render('[App][myogestic.App]\n\n::: myogestic.App');
        expect(code).toContain('[App][myogestic.App]');
        expect(code).toContain('::: myogestic.App');
    });

    it.each([['api/index.md', 11], ['widget-gallery.md', 15]] as const)('renders the existing %s card markup', async (page, cards) => {
        const processor = await createMarkdownProcessor({ remarkPlugins, rehypePlugins, syntaxHighlight: false });
        const fileURL = new URL(`../../../../docs/${page}`, import.meta.url);
        const source = readFileSync(fileURL, 'utf8').replace(/^---\n[\s\S]*?\n---\n/, '');
        const { code } = await processor.render(source, { fileURL });
        expect(code.match(/class="mg-card"/g)).toHaveLength(cards);
        expect(code).not.toContain(' markdown>');
        expect(code).not.toContain(':material-');
        expect(code).not.toContain(':octicons-');
        expect(code).not.toContain('.widget-thumb');
        expect(code).not.toContain('.middle');
        if (page === 'widget-gallery.md') {
            expect(code).toContain('<div class="gallery-nav">');
            expect(code).toContain('<div class="other-widgets">');
            expect(code).toContain('href="#signal-viewers"');
            expect(code.match(/loading="lazy"/g)).toHaveLength(15);
        }
    });
});
