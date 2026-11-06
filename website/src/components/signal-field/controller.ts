import { createCanvas2DRenderer } from './canvas2d';
import { createFieldState, GESTURES, mulberry32, setGesture, stepField, type Gesture } from './field';
import { createGLRenderer, FIELD_BACKGROUND_FALLBACK } from './gl';

export interface FieldEnv {
  raf(cb: FrameRequestCallback): number;
  caf(id: number): void;
  reducedMotion(): boolean;
  onVisibility(cb: (visible: boolean) => void): () => void;
  onIntersect(el: Element, cb: (inView: boolean) => void): () => void;
  onResize(el: Element, cb: (w: number, h: number) => void): () => void;
  dpr(): number;
}

const browserEnv: FieldEnv = {
  raf: (cb) => requestAnimationFrame(cb),
  caf: (id) => cancelAnimationFrame(id),
  reducedMotion: () => matchMedia('(prefers-reduced-motion: reduce)').matches,
  dpr: () => Math.min(2, window.devicePixelRatio || 1),
  onVisibility(cb) {
    const update = () => cb(!document.hidden);
    document.addEventListener('visibilitychange', update);
    update();
    return () => document.removeEventListener('visibilitychange', update);
  },
  onIntersect(el, cb) {
    const observer = new IntersectionObserver((entries) => cb(entries[0].isIntersecting));
    observer.observe(el);
    return () => observer.disconnect();
  },
  onResize(el, cb) {
    const box = el.getBoundingClientRect();
    cb(box.width, box.height);
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      cb(rect.width, rect.height);
    });
    observer.observe(el);
    return () => observer.disconnect();
  },
};

export function mountSignalField(canvas: HTMLCanvasElement, opts: {
  channels?: number;
  samplesPerFrame?: number;
  autoCycleMs?: number;
  onGesture?: (g: Gesture, auto: boolean) => void;
  env?: FieldEnv;
} = {}): { hold(g: Gesture): void; auto(): void; destroy(): void } {
  const env = opts.env ?? browserEnv;
  const state = createFieldState(opts.channels ?? 64);
  const samplesPerFrame = Math.max(1, Math.min(state.samples, Math.round(opts.samplesPerFrame ?? 4)));
  const autoCycleMs = Math.max(1, opts.autoCycleMs ?? 2800);
  const reduced = env.reducedMotion();
  const rand = mulberry32(7);
  // Read the inherited token once, before rendering or any frame is scheduled.
  const background = getComputedStyle(canvas).getPropertyValue('--mg-field-bg').trim() || FIELD_BACKGROUND_FALLBACK;
  let renderer = createGLRenderer(canvas, background, state.channels, state.samples);
  let usingGL = renderer !== null;
  renderer ??= createCanvas2DRenderer(canvas, background, state.channels, state.samples);
  let surface = renderer.canvas ?? canvas;
  let visible = false;
  let inView = false;
  let width = 0;
  let height = 0;
  let ready = false;
  let destroyed = false;
  let dirty = true;
  let held = false;
  let pending = -1;
  let inFrame = false;
  let cycleTimer: ReturnType<typeof setTimeout> | null = null;
  let remaining = autoCycleMs;
  let startedAt = 0;
  let removeIntersection: () => void;
  let removeResize: () => void;
  setGesture(state, 'Fist');
  renderer.upload(state, 0, state.samples);

  function stop(): void {
    if (pending >= 0) env.caf(pending);
    pending = -1;
    stopCycle();
  }
  function stopCycle(): void {
    if (cycleTimer === null) return;
    clearTimeout(cycleTimer);
    cycleTimer = null;
    remaining = Math.max(0, remaining - (Date.now() - startedAt));
  }
  function startCycle(): void {
    if (cycleTimer !== null || reduced || held || destroyed || !ready || !visible || !inView || width <= 0 || height <= 0) return;
    startedAt = Date.now();
    cycleTimer = setTimeout(cycle, remaining);
  }
  function cycle(): void {
    cycleTimer = null;
    if (destroyed || !visible || !inView || held) return;
    remaining = autoCycleMs;
    setGesture(state, GESTURES[(GESTURES.indexOf(state.gesture) + 1) % GESTURES.length]);
    announce();
    startCycle();
  }
  function sync(): void {
    if (!ready || destroyed) return;
    if (!visible || !inView || width <= 0 || height <= 0) {
      stop();
      return;
    }
    if (reduced) {
      if (dirty) {
        stepField(state, 120, rand);
        renderer!.upload(state, 0, state.samples);
        renderer!.draw(state);
        dirty = false;
      }
    } else {
      if (pending < 0 && !inFrame) pending = env.raf(frame);
      startCycle();
    }
  }
  function announce(): void {
    opts.onGesture?.(state.gesture, !held);
  }
  // Gesture notifications and clock arithmetic run in the separately paused
  // timer, so user UI updates and numeric boxing never enter the frame callback.
  function frame(): void {
    pending = -1;
    if (destroyed || !visible || !inView || width <= 0 || height <= 0) return;
    inFrame = true;
    const from = state.head;
    stepField(state, samplesPerFrame, rand);
    renderer!.upload(state, from, samplesPerFrame);
    renderer!.draw(state);
    inFrame = false;
    if (!destroyed && visible && inView) pending = env.raf(frame);
  }
  function visibility(value: boolean): void { visible = value; sync(); }
  function intersection(value: boolean): void { inView = value; sync(); }
  function resize(w: number, h: number): void {
    if (destroyed || (width === w && height === h)) return;
    width = w;
    height = h;
    renderer!.resize(w, h, Math.min(2, env.dpr()));
    dirty = true;
    sync();
  }
  function contextLost(event: Event): void {
    event.preventDefault();
    if (destroyed || !usingGL) return;
    stop();
    ready = false;
    surface.removeEventListener('webglcontextlost', contextLost);
    removeIntersection();
    removeResize();
    renderer!.destroy();
    renderer = createCanvas2DRenderer(surface, background, state.channels, state.samples);
    usingGL = false;
    surface = renderer.canvas ?? surface;
    renderer.resize(width, height, Math.min(2, env.dpr()));
    renderer.upload(state, 0, state.samples);
    dirty = true;
    inView = false;
    removeIntersection = env.onIntersect(surface, intersection);
    removeResize = env.onResize(surface, resize);
    ready = true;
    sync();
  }
  const removeVisibility = env.onVisibility(visibility);
  removeIntersection = env.onIntersect(surface, intersection);
  removeResize = env.onResize(surface, resize);
  surface.addEventListener('webglcontextlost', contextLost);
  announce();
  ready = true;
  sync();

  function hold(g: Gesture): void {
    if (destroyed) return;
    held = true;
    stopCycle();
    remaining = autoCycleMs;
    setGesture(state, g);
    dirty = true;
    announce();
    sync();
  }
  function auto(): void {
    if (destroyed) return;
    held = false;
    stopCycle();
    remaining = autoCycleMs;
    announce();
    sync();
  }
  function destroy(): void {
    if (destroyed) return;
    destroyed = true;
    stop();
    removeVisibility();
    removeIntersection();
    removeResize();
    surface.removeEventListener('webglcontextlost', contextLost);
    renderer!.destroy();
  }
  return { hold, auto, destroy };
}
