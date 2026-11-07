import type { PhrasingContent, Root } from 'mdast';
import type { Plugin } from 'unified';
import { SKIP, visit } from 'unist-util-visit';

// Only the shortcodes used in docs/. Inline paths use currentColor in both themes.
const paths: Record<string, string> = {
    'material-application-braces-outline': 'M8 3H4a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1h-4M3 7h18M10 10H9v3l-2 1 2 1v3h1m4-8h1v3l2 1-2 1v3h-1',
    'material-tune-variant': 'M3 6h8m4 0h6M3 12h2m4 0h12M3 18h12m4 0h2M11 3v6M5 9v6m10 0v6',
    'material-keyboard': 'M3 5h18v14H3ZM6 9h1m3 0h1m3 0h1m3 0h1M6 12h1m3 0h1m3 0h1m3 0h1M8 16h8',
    'material-access-point': 'M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14M8 8a6 6 0 0 0 0 8m8-8a6 6 0 0 1 0 8M12 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4',
    'material-export': 'M10 5H4v15h15v-6M12 3h9v9M21 3 10 14',
    'material-camera-outline': 'M3 7h5l2-3h4l2 3h5v13H3ZM12 9a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
    'material-brain': 'M12 4c-4-4-9 1-7 4-4 2-3 7 0 8-1 5 5 7 7 3 2 4 8 2 7-3 3-1 4-6 0-8 2-3-3-8-7-4Zm0 0v15M5 8l3 2m11-2-3 2M5 16l3-3m11 3-3-3',
    'material-widgets-outline': 'M3 3h7v7H3Zm11 0h7v7h-7ZM3 14h7v7H3Zm11 0h7v7h-7Z',
    'material-robot-outline': 'M5 7h14v13H5ZM12 3v4m-9 4v5m18-5v5M8 11h1m6 0h1m-8 5h8',
    'material-database-outline': 'M3 6a9 3 0 1 0 18 0 9 3 0 1 0-18 0Zm0 0v12c0 4 18 4 18 0V6M3 12c0 4 18 4 18 0',
    'material-filter-variant': 'M3 6h18M6 12h12m-9 6h6',
    'octicons-arrow-right-24': 'M4 12h16m-7-7 7 7-7 7',
    'material-arrow-right': 'M4 12h16m-7-7 7 7-7 7',
    'material-flask-outline': 'M9 3h6m-5 0v7L4 20h16l-6-10V3M7 15h10',
    'material-rocket-launch': 'M10 14c-3-6 3-11 11-11 0 8-5 14-11 11Zm1-8H6l-3 6h6m9 1v5l-6 3v-6M5 16l-2 5 5-2M16 7h1',
    'material-robot-industrial': 'M3 21h18M6 21v-5h5v5M8 16v-5l6-6 4 3-7 7M14 5l2-3 5 4-3 2m0 0 3 4-2 2',
    'material-puzzle-outline': 'M3 3h6c-2 6 8 6 6 0h6v6c-6-2-6 8 0 6v6h-6c2-6-8-6-6 0H3v-6c6 2 6-8 0-6Z',
    'material-school': 'M2 9 12 4l10 5-10 5Zm4 2v7c4 3 8 3 12 0v-7m4-2v9',
    'material-graph-outline': 'M3 3v18h18M6 16l5-6 4 3 6-8',
    'material-help-circle-outline': 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm-3 7c0-4 7-4 6 0 0 2-3 2-3 5m0 3h.01',
    'material-book-open-variant': 'M12 5C8 2 4 3 2 4v15c4-2 7-1 10 1 3-2 6-3 10-1V4c-2-1-6-2-10 1Zm0 0v15',
};

export const remarkIcons: Plugin<[], Root> = () => (tree, file) => {
    visit(tree, 'text', (node, index, parent) => {
        if (index === undefined || !parent) return;
        const matches = [...node.value.matchAll(/:(?:material|octicons|fontawesome)-[\w-]+:/g)];
        if (!matches.length) return;
        const nodes: PhrasingContent[] = [];
        let offset = 0;
        for (const match of matches) {
            const path = paths[match[0].slice(1, -1)];
            if (!path) throw new Error(`${file.path ?? '<markdown>'}:${node.position?.start.line ?? 1}: unknown icon ${match[0]}`);
            if (match.index! > offset) nodes.push({ type: 'text', value: node.value.slice(offset, match.index) });
            nodes.push({ type: 'html', value: `<svg class="mg-icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path fill="none" d="${path}"></path></svg>` });
            offset = match.index! + match[0].length;
        }
        if (offset < node.value.length) nodes.push({ type: 'text', value: node.value.slice(offset) });
        parent.children.splice(index, 1, ...nodes);
        return [SKIP, index + nodes.length];
    });
};
