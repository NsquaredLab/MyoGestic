import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

export const collections = {
    docs: defineCollection({
        loader: glob({
            pattern: ['**/*.md', '!superpowers/**', '!playground/**', '!index.md'],
            base: '../docs',
        }),
        schema: docsSchema(),
    }),
};
