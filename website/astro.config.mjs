// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { remarkPlugins, rehypePlugins } from './src/markdown/plugins';

export default defineConfig({
    site: 'https://nsquaredlab.github.io',
    base: '/MyoGestic',
    trailingSlash: 'always',
    build: { format: 'directory' },
    markdown: { remarkPlugins, rehypePlugins },
    integrations: [
        starlight({
            title: 'MyoGestic',
            logo: { src: './src/assets/brand/myogestic-horizontal.svg', replacesTitle: true },
            favicon: '/favicon.svg',
            head: [
                { tag: 'link', attrs: { rel: 'icon', href: '/MyoGestic/favicon.ico', sizes: 'any' } },
                { tag: 'link', attrs: { rel: 'apple-touch-icon', href: '/MyoGestic/apple-touch-icon.png' } },
            ],
            customCss: ['./src/styles/fonts.css', './src/styles/tokens.css'],
            components: {
                Head: './src/components/starlight/Head.astro',
                Header: './src/components/starlight/Header.astro',
                PageTitle: './src/components/starlight/PageTitle.astro',
                Sidebar: './src/components/starlight/Sidebar.astro',
                TableOfContents: './src/components/starlight/TableOfContents.astro',
                ThemeSelect: './src/components/starlight/ThemeSelect.astro',
                Footer: './src/components/starlight/Footer.astro',
            },
            social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/NsquaredLab/MyoGestic' }],
            sidebar: [
                // Starlight adds the configured base to local sidebar links.
                { label: 'Home', link: '/' },
                { label: 'Getting Started', slug: 'getting-started' },
                { label: 'Anatomy of an app', slug: 'anatomy' },
                {
                    label: 'Guides',
                    items: [
                        { label: 'Overview', slug: 'how-to' },
                        {
                            label: 'Start here',
                            items: [
                                { label: 'Overview', slug: 'tutorials' },
                                { label: 'EMG classification', slug: 'tutorials/emg-classification' },
                                { label: 'EMG regression with VHI', slug: 'tutorials/emg-regression-with-vhi' },
                                { label: 'Examples directory', slug: 'tutorials/examples-index' },
                            ],
                        },
                        {
                            label: 'Connecting hardware',
                            items: [
                                { label: 'Pick a device from the UI', slug: 'how-to/pick-a-device' },
                                { label: 'Connect OTB devices', slug: 'how-to/connect-otb-devices' },
                            ],
                        },
                        {
                            label: 'Driving a device',
                            items: [
                                { label: 'Drive your own device', slug: 'how-to/add-a-target' },
                                { label: 'Drive a remote target', slug: 'how-to/drive-a-remote-target' },
                                { label: 'Build a remote target, stage by stage', slug: 'tutorials/your-first-remote-target' },
                                { label: 'Integrate the Virtual Hand', slug: 'how-to/integrate-vhi' },
                                { label: 'Install the Virtual Hand', slug: 'how-to/install-vhi' },
                            ],
                        },
                        {
                            label: 'Recording',
                            items: [
                                { label: 'Enable on-disk recording', slug: 'how-to/enable-recording' },
                                { label: 'Record and replay', slug: 'how-to/record-and-replay' },
                                { label: 'Record good training data', slug: 'how-to/record-good-training-data' },
                                { label: 'Record for proportional control', slug: 'how-to/record-for-proportional-control' },
                                { label: 'Track a force target', slug: 'how-to/track-a-force-target' },
                            ],
                        },
                        {
                            label: 'Models and features',
                            items: [
                                { label: 'Add a custom model', slug: 'how-to/add-a-model' },
                                { label: 'Feature extraction cookbook', slug: 'how-to/feature-extraction-cookbook' },
                                { label: 'Use the recipe feature set', slug: 'how-to/use-recipe-features' },
                                { label: 'Keep state between pipeline stages', slug: 'how-to/inter-stage-state' },
                                { label: 'Post-process predictions', slug: 'how-to/post-process-output' },
                            ],
                        },
                        {
                            label: 'Extending the framework',
                            items: [
                                { label: 'Add a custom source', slug: 'how-to/add-a-source' },
                                { label: 'Add a custom widget', slug: 'how-to/add-a-widget' },
                                { label: 'Publish a data stream', slug: 'how-to/add-an-output' },
                            ],
                        },
                        { label: 'Operations', items: [{ label: 'Run headless (no GUI)', slug: 'how-to/headless-mode' }] },
                    ],
                },
                {
                    label: 'Concepts',
                    items: [
                        { label: 'Overview', slug: 'concepts' },
                        { label: 'Architecture', slug: 'concepts/architecture' },
                        { label: 'Streams', slug: 'concepts/streams' },
                        { label: 'Pipeline', slug: 'concepts/pipeline' },
                        { label: 'Controls', slug: 'concepts/controls' },
                        { label: 'Recording', slug: 'concepts/recording' },
                        { label: 'File names', slug: 'concepts/file-names' },
                        { label: 'Widgets', slug: 'concepts/widgets' },
                        { label: 'Grid layout', slug: 'concepts/grid-layout' },
                        { label: 'Edge trigger', slug: 'concepts/edge-trigger' },
                        { label: 'Threading', slug: 'concepts/threading' },
                        { label: 'Design principles', slug: 'concepts/design-principles' },
                        { label: 'Visual language', slug: 'concepts/visual-language' },
                    ],
                },
                { label: 'Widget gallery', slug: 'widget-gallery' },
                { label: 'Troubleshooting', slug: 'troubleshooting' },
                {
                    label: 'Reference',
                    items: [
                        { label: 'Overview', slug: 'reference' },
                        {
                            label: 'API reference',
                            items: [
                                { label: 'Overview', slug: 'api' },
                                { label: 'Core', slug: 'api/core' },
                                { label: 'Control standard', slug: 'api/controls' },
                                { label: 'Keyboard', slug: 'api/keyboard' },
                                { label: 'Sources', slug: 'api/sources' },
                                { label: 'Outlets', slug: 'api/outputs' },
                                { label: 'Bridges', slug: 'api/bridges' },
                                { label: 'ML pipeline', slug: 'api/ml' },
                                { label: 'Widgets', slug: 'api/widgets' },
                                { label: 'Models', slug: 'api/models' },
                                { label: 'Session', slug: 'api/session' },
                                { label: 'Filters', slug: 'api/filters' },
                            ],
                        },
                        { label: 'API cheatsheet', slug: 'reference/api-cheatsheet' },
                        { label: 'Glossary', slug: 'reference/glossary' },
                    ],
                },
            ],
        }),
    ],
});
