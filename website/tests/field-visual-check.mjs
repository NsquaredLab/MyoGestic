// Manual private-data check. Start field-reference.py SESSION --serve 4381 first.
// Recording arrays travel only from the loopback bridge into browser memory.
// Usage: node tests/field-visual-check.mjs [reference-url] [screenshot-directory] [site-url]
import { build } from 'esbuild';
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const source = fileURLToPath(new URL('../src/components/signal-field/', import.meta.url));
const out = resolve(process.argv[3] ?? '../.superpowers/screens');
await mkdir(out, { recursive: true });
const reference = await (await fetch(process.argv[2] ?? 'http://127.0.0.1:4381')).json();
const options = {
  stdin: { contents: `export * from './field'; export * from './gl';`, resolveDir: source },
  bundle: true, format: 'iife', globalName: 'F', write: false,
};
const current = (await build(options)).outputFiles[0].text;
// Compare the one-constant DPR 1 proposal with geometric strokes at the same gain.
const oldGL = execFileSync('git', ['show', '0c1afc6:website/src/components/signal-field/gl.ts'], { encoding: 'utf8' });
const previous = (await build({ ...options, globalName: 'Thin', plugins: [{
  name: 'previous-line-renderer', setup(build) {
    build.onLoad({ filter: /[/\\]gl\.ts$/ }, () => ({ contents: oldGL, loader: 'ts', resolveDir: source }));
  },
}] })).outputFiles[0].text;
const browser = await chromium.launch({ headless: true,
  args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=metal'] });
for (const dpr of [2, 1]) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: dpr });
  await page.setContent('<body style="margin:0;background:rgb(15,16,18);color:rgb(224,227,232);font:14px monospace"><main style="display:flex;height:900px"></main></body>');
  await page.addScriptTag({ content: current + '\n' + previous });
  const setup = ({ reference, mode, dpr }) => {
    document.querySelector('main').replaceChildren();
    const modes = mode === 'mappings' ? ['sample', 'minmax', 'native']
      : mode === 'thickness' ? ['DPR 1 line', 'Geometric stroke'] : ['Real · Rest → Fist', 'Synthetic · Rest → Fist'];
    for (const [j, label] of modes.entries()) {
      const w = 1440 / modes.length;
      const box = document.createElement('section');
      box.style.width = w + 'px';
      const p = document.createElement('p');
      p.style = 'height:22px;margin:14px 20px;';
      p.textContent = label;
      const canvas = document.createElement('canvas');
      canvas.style = 'width:' + w + 'px;height:850px';
      box.append(p, canvas); document.querySelector('main').append(box);
      let n = 480, data = null;
      if (mode === 'mappings') {
        data = reference.windows[label];
        if (label === 'minmax') {
          n = 960;
          data = reference.windows.min.map((row, c) => row.flatMap((v, i) => [v, reference.windows.max[c][i]]));
        }
      } else if (mode === 'reference' && j === 0) data = reference.windows.sample;
      const s = F.createFieldState(64, n);
      if (data) { s.data.set(data.flat()); s.act.set(reference.metrics.maps.Fist); }
      else {
        const rand = F.mulberry32(314159);
        F.setGesture(s, 'Rest'); F.stepField(s, 12000, rand);
        // Align the observed signal onset, which precedes the recorded Fist cue.
        const restColumns = Math.round((1.5 + reference.metrics.transitions.onset.delay_s) * 120);
        F.stepField(s, restColumns, rand); F.setGesture(s, 'Fist'); F.stepField(s, n - restColumns, rand);
      }
      const factory = mode === 'thickness' && j === 0 ? Thin : F;
      const renderer = factory.createGLRenderer(canvas, undefined, 64, n, true);
      renderer.resize(w, 850, mode === 'thickness' && j === 0 ? 1 : dpr);
      renderer.upload(s, 0, n); renderer.draw(s);
    }
    const gl = document.querySelector('canvas').getContext('webgl2');
    return gl.getParameter(gl.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL);
  };
  console.log(await page.evaluate(setup, { reference, mode: 'thickness', dpr }));
  await page.screenshot({ path: resolve(out, `field-thickness-${dpr}x.png`), scale: 'css' });
  if (dpr === 2) {
    await page.evaluate(setup, { reference, mode: 'mappings', dpr });
    await page.screenshot({ path: resolve(out, 'field-three-mappings.png'), scale: 'css' });
    await page.evaluate(setup, { reference, mode: 'reference', dpr });
    await page.screenshot({ path: resolve(out, 'field-real-vs-synthetic.png'), scale: 'css' });
  }
  await page.close();
}
if (process.argv[4]) {
  for (const [name, geometric] of [['dpr1', false], ['geometry', true]]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, reducedMotion: 'reduce' });
    await page.goto(process.argv[4], { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'Fist', exact: true }).click();
    await page.addScriptTag({ content: current + '\n' + previous });
    await page.evaluate((geometric) => {
      const canvas = document.querySelector('canvas');
      const s = F.createFieldState();
      F.setGesture(s, 'Fist'); F.stepField(s, 960, F.mulberry32(7));
      const renderer = (geometric ? F : Thin).createGLRenderer(canvas,
        getComputedStyle(canvas).getPropertyValue('--mg-field-bg').trim(), 64, 480, true);
      const box = canvas.getBoundingClientRect();
      renderer.resize(box.width, box.height, geometric ? 2 : 1);
      renderer.upload(s, 0, 480); renderer.draw(s);
    }, geometric);
    await page.screenshot({ path: resolve(out, `field-hero-${name}.png`), scale: 'css' });
    await page.close();
  }
}
await browser.close();
console.log('Saved comparisons to', out);
