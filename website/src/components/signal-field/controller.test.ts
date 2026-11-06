import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FieldEnv } from './controller';
import { mountSignalField } from './controller';

const mocks = vi.hoisted(() => ({ gl: vi.fn(), twoD: vi.fn() }));
vi.mock('./gl', () => ({ createGLRenderer: mocks.gl, FIELD_BACKGROUND_FALLBACK: '#0F1012' }));
vi.mock('./canvas2d', () => ({ createCanvas2DRenderer: mocks.twoD }));

function renderer() {
  return { resize: vi.fn(), upload: vi.fn(), draw: vi.fn(), destroy: vi.fn() };
}

class Environment implements FieldEnv {
  pending = new Map<number, FrameRequestCallback>();
  id = 0;
  time = 0;
  visible = true;
  inView = true;
  reduce = false;
  visibility!: (value: boolean) => void;
  intersection!: (value: boolean) => void;
  resize!: (w: number, h: number) => void;
  removals = [vi.fn(), vi.fn(), vi.fn()];
  raf = (cb: FrameRequestCallback) => { const id = ++this.id; this.pending.set(id, cb); return id; };
  caf = (id: number) => { this.pending.delete(id); };
  reducedMotion = () => this.reduce;
  dpr = () => 4;
  onVisibility = (cb: (value: boolean) => void) => {
    this.visibility = cb;
    cb(this.visible);
    return this.removals[0];
  };
  onIntersect = (_el: Element, cb: (value: boolean) => void) => {
    this.intersection = cb;
    cb(this.inView);
    return this.removals[1];
  };
  onResize = (_el: Element, cb: (w: number, h: number) => void) => {
    this.resize = cb;
    cb(1440, 800);
    return this.removals[2];
  };
  advance(ms = 16) {
    this.time += ms;
    vi.advanceTimersByTime(ms);
    const callbacks = [...this.pending.values()];
    this.pending.clear();
    for (const cb of callbacks) cb(this.time);
  }
  run(ms: number) { for (let i = 0; i < ms; i += 16) this.advance(); }
}

describe('signal field lifecycle', () => {
  let env: Environment;
  let canvas: HTMLCanvasElement;
  let gl: ReturnType<typeof renderer>;
  beforeEach(() => {
    vi.useFakeTimers();
    env = new Environment();
    canvas = new EventTarget() as HTMLCanvasElement;
    gl = renderer();
    mocks.gl.mockReset().mockReturnValue(gl);
    mocks.twoD.mockReset().mockImplementation(renderer);
    vi.stubGlobal('getComputedStyle', vi.fn(() => ({ getPropertyValue: () => ' rgb(15, 16, 18) ' })));
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it('schedules nothing while hidden or outside the viewport', () => {
    env.visible = false;
    const field = mountSignalField(canvas, { env });
    expect(env.pending.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    env.visibility(true);
    expect(env.pending.size).toBe(1);
    env.advance();
    expect(gl.draw).toHaveBeenCalledTimes(1);
    env.intersection(false);
    expect(env.pending.size).toBe(0);
    env.run(10000);
    expect(gl.draw).toHaveBeenCalledTimes(1);
    env.visibility(false);
    env.intersection(true);
    expect(env.pending.size).toBe(0);
    env.visibility(true);
    expect(env.pending.size).toBe(1);
    field.destroy();
    expect(env.pending.size).toBe(0);
    for (const cleanup of env.removals) expect(cleanup).toHaveBeenCalledOnce();
    env.visibility(true);
    expect(env.pending.size).toBe(0);
  });

  it('waits for intersection and nonzero size before starting', () => {
    env.inView = false;
    const field = mountSignalField(canvas, { env });
    expect(env.pending.size).toBe(0);
    env.intersection(true);
    env.resize(0, 0);
    expect(env.pending.size).toBe(0);
    env.resize(390, 844);
    expect(env.pending.size).toBe(1);
    expect(gl.resize).toHaveBeenLastCalledWith(390, 844, 2);
    field.destroy();
  });

  it('cancels a scheduler whose first request ID is zero', () => {
    env.id = -1;
    const field = mountSignalField(canvas, { env });
    expect(env.pending.has(0)).toBe(true);
    env.visibility(true);
    expect(env.pending.size).toBe(1);
    field.destroy();
    expect(env.pending.size).toBe(0);
  });

  it('renders one settled Fist frame for reduced motion with no automatic work', () => {
    env.reduce = true;
    const onGesture = vi.fn();
    const field = mountSignalField(canvas, { env, onGesture });
    expect(gl.draw).toHaveBeenCalledOnce();
    const s = gl.draw.mock.calls[0][0];
    expect(s.gesture).toBe('Fist');
    expect(s.head).toBe(120);
    expect(s.act[21]).toBeGreaterThan(0.85);
    expect(env.pending.size).toBe(0);
    onGesture.mockClear();
    env.run(10000);
    expect(onGesture).not.toHaveBeenCalled();
    expect(gl.draw).toHaveBeenCalledOnce();
    field.destroy();
  });

  it('holds a gesture and resumes cycling in gesture order', () => {
    const onGesture = vi.fn();
    const field = mountSignalField(canvas, { env, onGesture });
    field.hold('Pinch');
    expect(onGesture).toHaveBeenLastCalledWith('Pinch', false);
    onGesture.mockClear();
    env.run(10000);
    expect(onGesture).not.toHaveBeenCalled();
    field.auto();
    expect(onGesture).toHaveBeenLastCalledWith('Pinch', true);
    env.run(2900);
    expect(onGesture).toHaveBeenLastCalledWith('Rest', true);
    env.run(2900);
    expect(onGesture).toHaveBeenLastCalledWith('Fist', true);
    env.run(2900);
    expect(onGesture).toHaveBeenLastCalledWith('Open', true);
    field.destroy();
  });

  it('excludes suspended time from auto cycling', () => {
    const onGesture = vi.fn();
    const field = mountSignalField(canvas, { env, onGesture });
    env.run(2000);
    env.visibility(false);
    env.run(10000);
    env.visibility(true);
    env.advance();
    expect(onGesture).toHaveBeenLastCalledWith('Fist', true);
    env.run(900);
    expect(onGesture).toHaveBeenLastCalledWith('Open', true);
    field.destroy();
  });

  it('cycles on wall time independently of frame timestamps', () => {
    env.time = 2147483600;
    const onGesture = vi.fn();
    const field = mountSignalField(canvas, { env, autoCycleMs: 64, onGesture });
    env.run(96);
    expect(onGesture).toHaveBeenLastCalledWith('Open', true);
    field.destroy();
  });

  it('stops immediately if an automatic gesture callback destroys the field', () => {
    const field = mountSignalField(canvas, { env, onGesture(g) {
      if (g === 'Open') field.destroy();
    } });
    env.run(2900);
    const draws = gl.draw.mock.calls.length;
    expect(gl.destroy).toHaveBeenCalledOnce();
    expect(env.pending.size).toBe(0);
    env.run(1000);
    expect(gl.draw).toHaveBeenCalledTimes(draws);
  });

  it('reads the background token once and falls back on context loss', () => {
    const field = mountSignalField(canvas, { env });
    expect(mocks.gl.mock.calls[0][1]).toBe('rgb(15, 16, 18)');
    const lost = new Event('webglcontextlost', { cancelable: true });
    canvas.dispatchEvent(lost);
    expect(lost.defaultPrevented).toBe(true);
    expect(gl.destroy).toHaveBeenCalledOnce();
    expect(mocks.twoD).toHaveBeenCalledOnce();
    env.advance();
    expect(mocks.twoD.mock.results[0].value.draw).toHaveBeenCalledOnce();
    env.resize(800, 600);
    expect(getComputedStyle).toHaveBeenCalledOnce();
    field.destroy();
    canvas.dispatchEvent(new Event('webglcontextlost'));
    expect(mocks.twoD).toHaveBeenCalledOnce();
  });
});
