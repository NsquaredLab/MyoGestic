import { channelColor, type FieldState } from './field';

export const FIELD_BACKGROUND_FALLBACK = '#0F1012';

export interface Renderer {
  /** A fallback may replace a canvas whose context type is already locked. */
  readonly canvas?: HTMLCanvasElement;
  resize(cssW: number, cssH: number, dpr: number): void;
  upload(s: FieldState, from: number, count: number): void;
  draw(s: FieldState): void;
  destroy(): void;
}

// Probe before shader compilation so software WebGL never builds the full tier.
export function getRendererInfo(canvas: HTMLCanvasElement, preserveDrawingBuffer = false): string {
  const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer });
  const info = gl?.getExtension('WEBGL_debug_renderer_info');
  return info ? String(gl!.getParameter(info.UNMASKED_RENDERER_WEBGL)) : '';
}

export function createGLRenderer(
  canvas: HTMLCanvasElement,
  background = FIELD_BACKGROUND_FALLBACK,
  channels = 64,
  samples = 480,
  preserveDrawingBuffer = false,
): Renderer | null {
  const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, stencil: false, preserveDrawingBuffer });
  if (!gl) return null;

  const signal = gl.createTexture();
  const activation = gl.createTexture();
  const program = gl.createProgram();
  const vao = gl.createVertexArray();
  const vertex = gl.createShader(gl.VERTEX_SHADER);
  const fragment = gl.createShader(gl.FRAGMENT_SHADER);
  let destroyed = false;
  function destroy(): void {
    if (destroyed) return;
    destroyed = true;
    gl!.deleteTexture(signal);
    gl!.deleteTexture(activation);
    gl!.deleteVertexArray(vao);
    gl!.deleteProgram(program);
    gl!.deleteShader(vertex);
    gl!.deleteShader(fragment);
  }
  if (!signal || !activation || !program || !vao || !vertex || !fragment) {
    destroy();
    return null;
  }

  function texture(texture: WebGLTexture, unit: number, w: number, h: number): void {
    gl!.activeTexture(unit);
    gl!.bindTexture(gl!.TEXTURE_2D, texture);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MIN_FILTER, gl!.NEAREST);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_MAG_FILTER, gl!.NEAREST);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_S, gl!.CLAMP_TO_EDGE);
    gl!.texParameteri(gl!.TEXTURE_2D, gl!.TEXTURE_WRAP_T, gl!.CLAMP_TO_EDGE);
    gl!.texStorage2D(gl!.TEXTURE_2D, 1, gl!.R32F, w, h);
  }
  texture(signal, gl.TEXTURE0, samples, channels);
  texture(activation, gl.TEXTURE1, channels, 1);
  if (gl.getError() !== gl.NO_ERROR) {
    destroy();
    return null;
  }

  gl.shaderSource(vertex, `#version 300 es
precision highp float;
precision highp int;
uniform highp sampler2D uSignal;
uniform highp sampler2D uActivation;
uniform int uHead;
uniform vec3 uColors[${channels}];
out vec4 color;
void main() {
  int c = gl_InstanceID;
  int i = gl_VertexID;
  float v = texelFetch(uSignal, ivec2((uHead + i) % ${samples}, c), 0).r;
  float a = 0.22 + 0.6 * texelFetch(uActivation, ivec2(c, 0), 0).r;
  gl_Position = vec4(2.0 * float(i) / ${samples - 1}.0 - 1.0,
    1.0 - 2.0 * (float(c) + 0.5 - v * 2.4) / ${channels}.0, 0.0, 1.0);
  color = vec4(uColors[c] * a, a);
}`);
  gl.shaderSource(fragment, `#version 300 es
precision highp float;
in vec4 color;
out vec4 outputColor;
void main() { outputColor = color; }
`);
  gl.compileShader(vertex);
  gl.compileShader(fragment);
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getShaderParameter(vertex, gl.COMPILE_STATUS)
    || !gl.getShaderParameter(fragment, gl.COMPILE_STATUS)
    || !gl.getProgramParameter(program, gl.LINK_STATUS)) {
    destroy();
    return null;
  }
  gl.useProgram(program);
  gl.bindVertexArray(vao);
  gl.uniform1i(gl.getUniformLocation(program, 'uSignal'), 0);
  gl.uniform1i(gl.getUniformLocation(program, 'uActivation'), 1);
  const head = gl.getUniformLocation(program, 'uHead');
  const colors = new Float32Array(channels * 3);
  for (let c = 0; c < channels; c++) {
    const rgb = channelColor(c / Math.max(1, channels - 1));
    for (let i = 0; i < 3; i++) colors[c * 3 + i] = rgb[i] / 255;
  }
  gl.uniform3fv(gl.getUniformLocation(program, 'uColors[0]'), colors);

  // Resolve any CSS colour syntax once, outside the animation path.
  const swatch = canvas.ownerDocument.createElement('canvas');
  swatch.width = swatch.height = 1;
  const ctx = swatch.getContext('2d')!;
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, 1, 1);
  const rgb = ctx.getImageData(0, 0, 1, 1).data;
  gl.clearColor(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE);
  gl.disable(gl.DEPTH_TEST);

  // One fixed staging buffer. The WebGL2 srcOffset overload reads only w*h
  // values, so neither a subarray view nor a per-frame buffer is needed.
  const staging = new Float32Array(channels * samples);
  function columns(s: FieldState, from: number, count: number): void {
    for (let c = 0; c < channels; c++) {
      for (let i = 0; i < count; i++) staging[c * count + i] = s.data[c * samples + from + i];
    }
    gl!.texSubImage2D(gl!.TEXTURE_2D, 0, from, 0, count, channels, gl!.RED, gl!.FLOAT, staging, 0);
  }
  function upload(s: FieldState, from: number, count: number): void {
    gl!.activeTexture(gl!.TEXTURE0);
    gl!.bindTexture(gl!.TEXTURE_2D, signal);
    if (count >= samples) {
      columns(s, 0, samples);
    } else if (count > 0) {
      const first = Math.min(count, samples - from);
      columns(s, from, first);
      if (first < count) columns(s, 0, count - first);
    }
    gl!.activeTexture(gl!.TEXTURE1);
    gl!.bindTexture(gl!.TEXTURE_2D, activation);
    gl!.texSubImage2D(gl!.TEXTURE_2D, 0, 0, 0, channels, 1, gl!.RED, gl!.FLOAT, s.act, 0);
  }
  function draw(s: FieldState): void {
    gl!.clear(gl!.COLOR_BUFFER_BIT);
    gl!.uniform1i(head, s.head);
    gl!.drawArraysInstanced(gl!.LINE_STRIP, 0, samples, channels);
  }
  function resize(w: number, h: number, dpr: number): void {
    dpr = Math.min(2, dpr);
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    gl!.viewport(0, 0, canvas.width, canvas.height);
    gl!.lineWidth(dpr);
  }
  return { canvas, resize, upload, draw, destroy };
}
