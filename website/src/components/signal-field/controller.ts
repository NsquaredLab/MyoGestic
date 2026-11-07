import { createCanvas2DRenderer } from './canvas2d';
import { createFieldState, GESTURES, mulberry32, setGesture, stepField, type Gesture } from './field';
import { createGLRenderer, FIELD_BACKGROUND_FALLBACK, getRendererInfo } from './gl';

export interface FieldEnv {
  raf(cb: FrameRequestCallback): number;
  caf(id: number): void;
  reducedMotion(): boolean;
  onVisibility(cb: (visible: boolean) => void): () => void;
  onIntersect(el: Element, cb: (inView: boolean) => void): () => void;
  onResize(el: Element, cb: (w: number, h: number) => void): () => void;
  dpr(): number;
  now(): number;
  onLoad(cb: () => void): () => void;
  idle(cb: () => void): number;
  cancelIdle(id: number): void;
}

const browserEnv: FieldEnv = {
  raf: (cb) => requestAnimationFrame(cb),
  caf: (id) => cancelAnimationFrame(id),
  reducedMotion: () => matchMedia('(prefers-reduced-motion: reduce)').matches,
  dpr: () => Math.min(2, window.devicePixelRatio || 1),
  now: () => performance.now(),
  onLoad(cb) {
    if (document.readyState === 'complete') cb();
    else window.addEventListener('load', cb, { once: true });
    return () => window.removeEventListener('load', cb);
  },
  idle: (cb) => window.requestIdleCallback
    ? window.requestIdleCallback(cb, { timeout: 1500 })
    : window.setTimeout(cb, 0),
  cancelIdle: (id) => window.cancelIdleCallback ? window.cancelIdleCallback(id) : window.clearTimeout(id),
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

interface FieldOptions {
  channels?: number;
  samplesPerFrame?: number;
  autoCycleMs?: number;
  onGesture?: (g: Gesture, auto: boolean) => void;
  env?: FieldEnv;
}

interface FieldController { hold(g: Gesture): void; auto(): void; destroy(): void }

/** Keep controls usable while all renderer work waits for load and idle. */
export function mountSignalFieldAfterLoad(canvas: HTMLCanvasElement, opts: FieldOptions = {}): FieldController {
  const env = opts.env ?? browserEnv;
  let controller: FieldController | null = null;
  let pending = -1;
  let destroyed = false;
  let gesture: Gesture = 'Fist';
  let held = false;
  function start(): void {
    pending = -1;
    if (destroyed) return;
    controller = mountSignalField(canvas, opts);
    if (held || gesture !== 'Fist') {
      controller.hold(gesture);
      if (!held) controller.auto();
    }
  }
  const removeLoad = env.onLoad(() => {
    if (!destroyed) pending = env.idle(start);
  });
  return {
    hold(g) {
      if (destroyed) return;
      gesture = g;
      held = true;
      if (controller) controller.hold(g);
      else opts.onGesture?.(g, false);
    },
    auto() {
      if (destroyed) return;
      held = false;
      if (controller) controller.auto();
      else opts.onGesture?.(gesture, true);
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      removeLoad();
      if (pending >= 0) env.cancelIdle(pending);
      controller?.destroy();
    },
  };
}

export function mountSignalField(canvas: HTMLCanvasElement, opts: FieldOptions = {}): FieldController {
  const env = opts.env ?? browserEnv;
  const reduced = env.reducedMotion();
  // Tiers only descend: full (0), reduced (1), still (2).
  const info = reduced ? getRendererInfo(canvas, true) : getRendererInfo(canvas);
  const software = /SwiftShader|llvmpipe|Software|Microsoft Basic Render/i.test(info);
  let tier = software ? 1 : 0;
  let state = createFieldState(tier === 0 ? opts.channels ?? 64 : 32, tier === 0 ? 480 : 240);
  const samplesPerFrame = Math.max(1, Math.min(state.samples, Math.round(opts.samplesPerFrame ?? 2)));
  const autoCycleMs = Math.max(1, opts.autoCycleMs ?? 2800);
  const rand = mulberry32(7);
  // Read the inherited token once, before rendering or any frame is scheduled.
  const background = getComputedStyle(canvas).getPropertyValue('--mg-field-bg').trim() || FIELD_BACKGROUND_FALLBACK;
  // A still must retain its pixels after compositing; animated contexts keep
  // the existing default so their GPU performance is unchanged.
  // Software WebGL compiles the geometry shader synchronously for about a
  // second. The existing 2D fallback keeps the same reduced-tier cadence and
  // density without making page startup wait for that compilation.
  let renderer = software ? null : reduced
    ? createGLRenderer(canvas, background, state.channels, state.samples, true)
    : createGLRenderer(canvas, background, state.channels, state.samples);
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
  let skip = false;
  const costs = new Float64Array(30);
  let measured = 0;
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
    if (cycleTimer !== null || reduced || tier === 2 || held || destroyed || !ready || !visible || !inView || width <= 0 || height <= 0) return;
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
    if (reduced || tier === 2) {
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
    // Reduced draws every other rAF. Skipped callbacks are never measured.
    if (tier === 1) {
      skip = !skip;
      if (skip) {
        pending = env.raf(frame);
        return;
      }
    }
    inFrame = true;
    if (measured < costs.length) costs[measured] = env.now();
    const from = state.head;
    stepField(state, samplesPerFrame, rand);
    renderer!.upload(state, from, samplesPerFrame);
    renderer!.draw(state);
    if (measured < costs.length) {
      costs[measured] = env.now() - costs[measured];
      measured = (measured + 1) | 0;
      if (measured === costs.length) {
        let total = 0;
        for (let i = 0; i < costs.length; i++) total += costs[i];
        if (total > 4 * costs.length) stepDown();
      }
    }
    inFrame = false;
    if (!destroyed && visible && inView && tier !== 2) pending = env.raf(frame);
  }
  // The only allocation after startup is a tier change, never a steady frame.
  function stepDown(): void {
    tier++;
    if (tier === 2) {
      dirty = false; // The frame just drawn is the current gesture's still.
      stopCycle();
      return;
    }
    measured = 0;
    skip = false;
    const gesture = state.gesture;
    state = createFieldState(32, 240);
    setGesture(state, gesture);
    stepField(state, 120, rand);
    renderer!.destroy();
    renderer = usingGL ? createGLRenderer(surface, background, state.channels, state.samples) : null;
    usingGL = renderer !== null;
    renderer ??= createCanvas2DRenderer(surface, background, state.channels, state.samples);
    observeSurface();
    renderer.resize(width, height, 1);
    renderer.upload(state, 0, state.samples);
  }
  function observeSurface(): void {
    const next = renderer!.canvas ?? surface;
    if (next === surface) return;
    surface.removeEventListener('webglcontextlost', contextLost);
    removeIntersection();
    removeResize();
    surface = next;
    surface.addEventListener('webglcontextlost', contextLost);
    inView = false;
    removeIntersection = env.onIntersect(surface, intersection);
    removeResize = env.onResize(surface, resize);
  }
  function visibility(value: boolean): void { visible = value; sync(); }
  function intersection(value: boolean): void { inView = value; sync(); }
  function resize(w: number, h: number): void {
    if (destroyed || (width === w && height === h)) return;
    width = w;
    height = h;
    renderer!.resize(w, h, tier === 0 ? Math.min(2, env.dpr()) : 1);
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
    renderer.resize(width, height, tier === 0 ? Math.min(2, env.dpr()) : 1);
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
