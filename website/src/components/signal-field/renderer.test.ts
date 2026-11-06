import { afterEach, describe, expect, it, vi } from 'vitest';
import { createCanvas2DRenderer } from './canvas2d';
import * as field from './field';
import { createGLRenderer } from './gl';

function context2D() {
  return {
    fillStyle: '', strokeStyle: '', globalCompositeOperation: '', lineWidth: 0,
    setTransform: vi.fn(), fillRect: vi.fn(), getImageData: () => ({ data: [15, 16, 18, 255] }),
    beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn(),
  };
}

function contextGL() {
  const gl: Record<string, any> = {};
  const constants = ['TEXTURE_2D', 'TEXTURE_MIN_FILTER', 'TEXTURE_MAG_FILTER', 'NEAREST', 'TEXTURE_WRAP_S',
    'TEXTURE_WRAP_T', 'CLAMP_TO_EDGE', 'R32F', 'TEXTURE0', 'TEXTURE1', 'VERTEX_SHADER', 'FRAGMENT_SHADER',
    'COMPILE_STATUS', 'LINK_STATUS', 'BLEND', 'ONE', 'DEPTH_TEST', 'RED', 'FLOAT', 'COLOR_BUFFER_BIT', 'LINE_STRIP'];
  constants.forEach((name, i) => { gl[name] = i + 1; });
  for (const name of ['createTexture', 'createProgram', 'createVertexArray', 'createShader', 'getUniformLocation']) {
    gl[name] = vi.fn(() => ({}));
  }
  for (const name of ['deleteTexture', 'deleteVertexArray', 'deleteProgram', 'deleteShader', 'activeTexture',
    'bindTexture', 'texParameteri', 'texStorage2D', 'shaderSource', 'compileShader', 'attachShader', 'linkProgram',
    'useProgram', 'bindVertexArray', 'uniform1i', 'uniform3fv', 'clearColor', 'enable', 'blendFunc', 'disable',
    'texSubImage2D', 'clear', 'drawArraysInstanced', 'viewport', 'lineWidth']) gl[name] = vi.fn();
  gl.NO_ERROR = 0;
  gl.getError = vi.fn(() => 0);
  gl.getShaderParameter = vi.fn(() => true);
  gl.getProgramParameter = vi.fn(() => true);
  return gl;
}

function canvas(gl: ReturnType<typeof contextGL> | null, ctx = context2D()) {
  const replacement: any = {
    width: 0, height: 0, getContext: vi.fn(() => ctx),
  };
  const original: any = {
    width: 0, height: 0,
    getContext: vi.fn((type: string) => type === 'webgl2' ? gl : gl ? null : ctx),
    ownerDocument: { createElement: () => ({ getContext: () => ctx }) },
    cloneNode: vi.fn(() => replacement), replaceWith: vi.fn(),
  };
  return { original: original as HTMLCanvasElement, replacement, ctx };
}

afterEach(() => vi.restoreAllMocks());

describe('WebGL renderer', () => {
  it('allocates just 123136 texture bytes and draws all channels in one call', () => {
    const gl = contextGL();
    const { original } = canvas(gl);
    const renderer = createGLRenderer(original)!;
    expect(renderer).not.toBeNull();
    const bytes = gl.texStorage2D.mock.calls.reduce((sum: number, call: number[]) => sum + call[3] * call[4] * 4, 0);
    expect(bytes).toBe(123136);
    expect(bytes).toBeLessThanOrEqual(256 * 1024);
    expect(gl.texStorage2D).toHaveBeenCalledTimes(2);
    renderer.resize(1440, 800, 4);
    expect(original.width).toBe(2880);
    expect(original.height).toBe(1600);
    const s = field.createFieldState();
    renderer.upload(s, 0, s.samples);
    renderer.draw(s);
    expect(gl.drawArraysInstanced).toHaveBeenCalledExactlyOnceWith(gl.LINE_STRIP, 0, 480, 64);
    expect(gl.blendFunc).toHaveBeenCalledWith(gl.ONE, gl.ONE);
    renderer.destroy();
    renderer.destroy();
    expect(gl.deleteTexture).toHaveBeenCalledTimes(2);
  });

  it('packs only changed columns and splits wrapped uploads using the same staging array', () => {
    const gl = contextGL();
    const renderer = createGLRenderer(canvas(gl).original, 'rgb(15, 16, 18)', 2, 8)!;
    const s = field.createFieldState(2, 8);
    for (let i = 0; i < s.data.length; i++) s.data[i] = i;
    const snapshots: { x: number; w: number; h: number; data: number[]; identity: Float32Array }[] = [];
    gl.texSubImage2D.mockImplementation((...args: any[]) => {
      snapshots.push({ x: args[2], w: args[4], h: args[5],
        data: Array.from(args[8]).slice(0, args[4] * args[5]), identity: args[8] });
    });
    const subarray = vi.spyOn(Float32Array.prototype, 'subarray');
    renderer.upload(s, 6, 4);
    expect(snapshots[0]).toMatchObject({ x: 6, w: 2, h: 2, data: [6, 7, 14, 15] });
    expect(snapshots[1]).toMatchObject({ x: 0, w: 2, h: 2, data: [0, 1, 8, 9] });
    expect(snapshots[0].identity).toBe(snapshots[1].identity);
    expect(snapshots[2].identity).toBe(s.act);
    renderer.upload(s, 2, 3);
    expect(snapshots[3]).toMatchObject({ x: 2, w: 3, h: 2, data: [2, 3, 4, 10, 11, 12] });
    expect(snapshots[3].identity).toBe(snapshots[0].identity);
    expect(gl.texStorage2D).toHaveBeenCalledTimes(2);
    expect(subarray).not.toHaveBeenCalled();
    renderer.destroy();
  });

  it('returns null for unavailable WebGL2, unsupported R32F, or failed shaders', () => {
    expect(createGLRenderer(canvas(null).original)).toBeNull();
    const gl = contextGL();
    gl.getError.mockReturnValue(1);
    expect(createGLRenderer(canvas(gl).original)).toBeNull();
    expect(gl.deleteTexture).toHaveBeenCalledTimes(2);
    const failed = contextGL();
    failed.getProgramParameter.mockReturnValue(false);
    expect(createGLRenderer(canvas(failed).original)).toBeNull();
    expect(failed.deleteProgram).toHaveBeenCalledOnce();
  });
});

describe('Canvas 2D fallback', () => {
  it('replaces a context-locked canvas and precomputes all stroke styles', () => {
    const { original, replacement, ctx } = canvas(contextGL());
    const colors = vi.spyOn(field, 'channelColor');
    const renderer = createCanvas2DRenderer(original, 'rgb(15, 16, 18)', 2, 8);
    expect(original.cloneNode).toHaveBeenCalledWith(false);
    expect(original.replaceWith).toHaveBeenCalledWith(replacement);
    expect(renderer.canvas).toBe(replacement);
    expect(colors).toHaveBeenCalledTimes(2);
    renderer.resize(390, 844, 4);
    expect(replacement.width).toBe(780);
    expect(ctx.setTransform).toHaveBeenCalledWith(2 / 256, 0, 0, 2 / 256, 0, 0);
    const s = field.createFieldState(2, 8);
    s.head = 6;
    s.data[6] = 1;
    renderer.upload(s, 0, 8);
    renderer.draw(s);
    renderer.draw(s);
    expect(ctx.moveTo.mock.calls[0][0]).toBe(0);
    expect(ctx.moveTo.mock.calls[0][1] / 256).toBeCloseTo(211 - 422 * 2.4, 2);
    expect(ctx.lineTo).toHaveBeenCalledTimes(28);
    expect(ctx.stroke).toHaveBeenCalledTimes(4);
    expect(colors).toHaveBeenCalledTimes(2);
    expect(ctx.fillStyle).toBe('rgb(15, 16, 18)');
    expect(ctx.strokeStyle).toBe('rgba(177,132,217,0.21875)');
    expect(ctx.globalCompositeOperation).toBe('source-over');
    renderer.resize(390, 422, 4);
    renderer.draw(s);
    expect(ctx.moveTo.mock.calls.at(-2)![1] / 256).toBeCloseTo(105.5 - 211 * 2.4, 2);
    expect(ctx.lineTo.mock.calls.every(([x, y]) => Number.isInteger(x) && Number.isInteger(y))).toBe(true);
    renderer.destroy();
  });
});
