import { describe, expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import { remarkApiDirective } from './directive';
import type { ApiData } from './render';

export const data: ApiData = {
    pages: {},
    symbols: {
        'myogestic.ml.Pipeline': { kind: 'class', path: 'myogestic.ml.Pipeline', name: 'Pipeline', signature: 'Pipeline(predict_hz: float = 50)', labels: [], bases: [], docstring: [{ kind: 'text', value: 'An **EMG** pipeline with `code`.\n\n- First\n- Second' }], members: ['myogestic.ml.Pipeline.run', 'myogestic.ml.Pipeline.stop'] },
        'myogestic.ml.Pipeline.run': { kind: 'function', path: 'myogestic.ml.Pipeline.run', name: 'run', signature: 'run() -> None', labels: [], bases: [], docstring: [], members: [] },
        'myogestic.ml.Pipeline.stop': { kind: 'function', path: 'myogestic.ml.Pipeline.stop', name: 'stop', signature: 'stop() -> None', labels: [], bases: [], docstring: [], members: [] },
    },
    inventory: { 'myogestic.ml.Pipeline': '/MyoGestic/api/ml/#myogestic.ml.Pipeline' },
};

function render(source: string) {
    const processor = unified().use(remarkParse).use(remarkApiDirective, { data });
    return JSON.stringify(processor.runSync(processor.parse(source), { path: '/docs/api/ml.md', value: source }));
}

describe('API directives', () => {
    it('consumes the options block and renders only selected members', () => {
        const result = render('Before\n\n::: myogestic.ml.Pipeline\n    options:\n      members: [run]\n\nAfter');
        expect(result).toContain('myogestic.ml.Pipeline');
        expect(result).toContain('mg-signature');
        expect(result).toContain('myogestic.ml.Pipeline.run');
        expect(result).not.toContain('myogestic.ml.Pipeline.stop');
        expect(result).not.toContain('options:');
        expect(result).toContain('Before');
        expect(result).toContain('After');
        expect(result).toContain('strong');
        expect(result).toContain('inlineCode');
        expect(result).toContain('listItem');
    });

    it('preserves adjacent directives without blank lines and code examples', () => {
        const result = render('::: myogestic.ml.Pipeline\n::: myogestic.ml.Pipeline.run\n\n```python\n::: myogestic.nope.Thing\n```');
        expect(result).toContain('mg-signature');
        expect(result).toContain('"type":"code"');
    });

    it('fails on unknown directives with page and line', () => {
        expect(() => render('Hello\n\n::: myogestic.nope.Thing')).toThrow(/ml.md:3.*myogestic.nope.Thing/);
    });
});
