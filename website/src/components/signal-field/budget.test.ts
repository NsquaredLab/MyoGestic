import { build } from 'esbuild';
import { gzipSync } from 'node:zlib';
import { expect, it } from 'vitest';

it('keeps the complete framework-free island within 10 KiB gzipped', async () => {
  const result = await build({
    entryPoints: ['src/components/signal-field/index.ts'],
    bundle: true, minify: true, format: 'esm', write: false,
  });
  const bytes = gzipSync(result.outputFiles[0].contents).length;
  console.info(`Signal field island: ${bytes} bytes gzipped (limit 10240)`);
  expect(bytes).toBeLessThanOrEqual(10240);
});
