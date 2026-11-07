// Private comparison: field-reference.py --group TAKE... --serve PORT.
// Arrays travel from the loopback bridge into browser memory only; PNG evidence
// stays local. Usage: node tests/field-visual-check.mjs BRIDGE_URL OUT_DIR SITE_URL
import { build } from 'esbuild';
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const source = fileURLToPath(new URL('../src/components/signal-field/', import.meta.url));
const out = resolve(process.argv[3]);
await mkdir(out, { recursive: true });
const bridge = new URL(process.argv[2]);
if (!['127.0.0.1', 'localhost', '[::1]'].includes(bridge.hostname)) throw Error('Reference bridge must be loopback');
const reference = await (await fetch(bridge)).json();
const code = (await build({
  stdin: { contents: `export * from './field'; export * from './gl';`, resolveDir: source },
  bundle: true, format: 'iife', globalName: 'F', write: false,
})).outputFiles[0].text;
const browser = await chromium.launch({ headless: true,
  args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=metal'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  await page.setContent('<body style="margin:0;background:rgb(15,16,18);color:rgb(224,227,232);font:14px monospace"><main style="display:flex;height:900px"></main></body>');
  await page.addScriptTag({ content: code });
  console.log(await page.evaluate((reference) => {
    for (const [j, label] of ['Real · 8-channel forearm bracelet recordings', 'Synthetic · fitted field'].entries()) {
      const box = document.createElement('section'); box.style.width = '720px';
      const title = document.createElement('p'); title.style = 'height:22px;margin:14px 20px'; title.textContent = label;
      const labels = document.createElement('div'); labels.style = 'display:grid;grid-template-columns:repeat(4,1fr);text-align:center;height:30px';
      for (const gesture of F.GESTURES) { const el = document.createElement('span'); el.textContent = gesture; labels.append(el); }
      const canvas = document.createElement('canvas'); canvas.style = 'width:720px;height:810px';
      box.append(title, labels, canvas); document.querySelector('main').append(box);
      const state = F.createFieldState();
      if (j === 0) state.data.set(reference.window.flat());
      else {
        const rand = F.mulberry32(314159);
        F.stepField(state, 2400, rand);
        for (const g of F.GESTURES) { F.setGesture(state, g); F.stepField(state, 120, rand); }
      }
      F.setGesture(state, 'Fist'); state.act.set(state.target);
      const renderer = F.createGLRenderer(canvas, undefined, 64, 480, true);
      if (!renderer) throw Error('Comparison requires WebGL2');
      renderer.resize(720, 810, 2); renderer.upload(state, 0, 480); renderer.draw(state);
    }
    const gl = document.querySelector('canvas').getContext('webgl2');
    return gl.getParameter(gl.getExtension('WEBGL_debug_renderer_info').UNMASKED_RENDERER_WEBGL);
  }, reference));
  await page.screenshot({ path: resolve(out, 'field-real-vs-synthetic-v2.png'), scale: 'css' });
  await page.goto(process.argv[4], { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  for (const gesture of ['Rest', 'Fist', 'Pinch', 'Index']) {
    await page.getByRole('button', { name: gesture, exact: true }).click();
    await page.waitForTimeout(4500);
    await page.screenshot({ path: resolve(out, `field-hero-${gesture.toLowerCase()}-v2.png`), scale: 'css' });
  }
  await page.close();
} finally {
  await browser.close();
}
console.log('Saved comparisons to', out);
