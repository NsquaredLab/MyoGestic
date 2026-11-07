import { channelColor, FIELD_GAIN, FIELD_HOT, type FieldState } from './field';
import { FIELD_BACKGROUND_FALLBACK, type Renderer } from './gl';

export function createCanvas2DRenderer(
  canvas: HTMLCanvasElement,
  background = FIELD_BACKGROUND_FALLBACK,
  channels = 64,
  samples = 480,
): Renderer {
  channels |= 0;
  samples |= 0;
  let context = canvas.getContext('2d', { alpha: false });
  if (!context) {
    // A WebGL canvas cannot acquire a second context type, even after loss.
    const replacement = canvas.cloneNode(false) as HTMLCanvasElement;
    canvas.replaceWith(replacement);
    canvas = replacement;
    context = canvas.getContext('2d', { alpha: false });
  }
  if (!context) throw new Error('A Canvas 2D context is required for the signal field.');
  const ctx = context;
  const styles: string[] = [];
  for (let c = 0; c < channels; c++) {
    const rgb = channelColor(c / Math.max(1, channels - 1));
    // Join into flat strings now. Lazy template-string ropes can otherwise
    // allocate when Canvas first reads a new colour during a gesture change.
    // Per-channel heat by activation: brighter and whiter as the channel works harder.
    for (let a = 0; a <= 32; a++) {
      const t = a / 32;
      const mix = (k: number) => Math.round(rgb[k] + (FIELD_HOT[k] - rgb[k]) * 0.8 * t * t);
      styles.push(['rgba(', mix(0), ',', mix(1), ',', mix(2), ',', 0.22 + 0.6 * t, ')'].join(''));
    }
  }
  // Fixed-point coordinates retain 1/256 CSS-pixel precision while passing
  // integers across the Canvas binding.
  const xs = new Int32Array(samples);
  const ys = new Int32Array(channels);
  const alphas = new Uint8Array(channels);
  const pixels = new Int32Array(channels * samples);
  const cursor = new Int32Array(1);
  let width = 0;
  let height = 0;
  let amplitude = 0;
  let lastState: FieldState | null = null;
  function resize(w: number, h: number, dpr: number): void {
    width = Math.round(w * 256);
    height = Math.round(h * 256);
    const row = height / channels;
    amplitude = row * FIELD_GAIN;
    for (let i = 0; i < samples; i++) xs[i] = Math.round(i / (samples - 1) * width);
    for (let c = 0; c < channels; c++) ys[c] = Math.round((c + 0.5) * row);
    dpr = Math.min(2, dpr);
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr / 256, 0, 0, dpr / 256, 0, 0);
    ctx.lineWidth = 512;
    if (lastState) upload(lastState, 0, samples);
  }
  // The draw path reads only cached integer coordinates and cached strings.
  function trace(c: number): void {
    const y = ys[c];
    ctx.strokeStyle = styles[c * 33 + alphas[c]];
    ctx.beginPath();
    for (let i = 0; i < samples; i++) {
      const x = xs[i];
      const v = (y - pixels[c * samples + (cursor[0] + i) % samples]) | 0;
      if (i === 0) ctx.moveTo(x, v);
      else ctx.lineTo(x, v);
    }
    ctx.stroke();
  }
  function draw(_s: FieldState): void {
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);
    for (let c = 0; c < channels; c++) trace(c);
    ctx.globalCompositeOperation = 'source-over';
  }
  function upload(s: FieldState, _from: number, _count: number): void {
    lastState = s;
    cursor[0] = s.head | 0;
    const count = Math.min(samples, _count);
    for (let c = 0; c < channels; c++) {
      alphas[c] = Math.min(32, Math.max(0, (s.act[c] * 32 + 0.5) | 0));
      for (let i = 0; i < count; i++) {
        const index = c * samples + (_from + i) % samples;
        pixels[index] = (s.data[index] * amplitude) | 0;
      }
    }
  }
  function destroy(): void { canvas.width = canvas.height = 1; }
  return { canvas, resize, upload, draw, destroy };
}
