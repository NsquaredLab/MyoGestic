export type Gesture = 'Rest' | 'Fist' | 'Open' | 'Pinch';
export const GESTURES: readonly Gesture[] = ['Rest', 'Fist', 'Open', 'Pinch'];
export const CONFIDENCE: Record<Gesture, number> = { Rest: 0.97, Fist: 0.94, Open: 0.91, Pinch: 0.88 };

const PATTERNS: Record<Gesture, readonly (readonly [number, number, number])[]> = {
  Rest: [],
  Fist: [[0.34, 0.2, 0.95], [0.74, 0.09, 0.55]],
  Open: [[0.7, 0.16, 0.9], [0.18, 0.07, 0.35]],
  Pinch: [[0.16, 0.06, 0.9], [0.46, 0.05, 0.5]],
};
const patternCache = new WeakMap<FieldState, Record<Gesture, Float32Array>>();

export interface FieldState {
  channels: number;
  samples: number;
  head: number;
  data: Float32Array;
  act: Float32Array;
  target: Float32Array;
  gesture: Gesture;
}

export function mulberry32(seed: number): () => number {
  // A captured 32-bit numeric seed can box a HeapNumber on every update in V8
  // (its small-integer range is narrower). Keep mutable numeric state in a buffer.
  const word = new Int32Array(1);
  word[0] = seed;
  return () => {
    word[0] = (word[0] + 0x6d2b79f5) | 0;
    const n = word[0];
    let t = Math.imul(n ^ (n >>> 15), 1 | n);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function createFieldState(channels = 64, samples = 480): FieldState {
  if (!Number.isInteger(channels) || channels < 1 || !Number.isInteger(samples) || samples < 2) {
    throw new RangeError('The signal field needs at least one channel and two samples.');
  }
  const state: FieldState = {
    channels, samples, head: 0,
    data: new Float32Array(channels * samples),
    act: new Float32Array(channels),
    target: new Float32Array(channels),
    gesture: 'Rest',
  };
  const patterns: Record<Gesture, Float32Array> = {
    Rest: new Float32Array(channels), Fist: new Float32Array(channels),
    Open: new Float32Array(channels), Pinch: new Float32Array(channels),
  };
  for (const gesture of GESTURES) fillPattern(patterns[gesture], channels, gesture);
  patternCache.set(state, patterns);
  return state;
}

function fillPattern(target: Float32Array, channels: number, gesture: Gesture): void {
  const pattern = PATTERNS[gesture];
  for (let c = 0; c < channels; c++) {
    const u = c / Math.max(1, channels - 1);
    let a = 0;
    for (let i = 0; i < pattern.length; i++) {
      const p = pattern[i];
      const d = (u - p[0]) / p[1];
      a += p[2] * Math.exp(-0.5 * d * d);
    }
    target[c] = Math.min(1, a);
  }
}

export function setGesture(s: FieldState, gesture: Gesture): void {
  const cached = patternCache.get(s);
  if (cached) s.target.set(cached[gesture]);
  else fillPattern(s.target, s.channels, gesture);
  s.gesture = gesture;
}

/** Trace height in channel lanes per unit of signal: bulk activity stays inside its lane. */
export const FIELD_GAIN = 0.4;

// Hot path: mutate the existing row-major ring and activation arrays only.
export function stepField(s: FieldState, k: number, rand: () => number): void {
  for (let i = 0; i < k; i++) {
    for (let c = 0; c < s.channels; c++) {
      s.act[c] += (s.target[c] - s.act[c]) * 0.02;
      const a = 0.05 + s.act[c];
      let v = (rand() + rand() + rand() - 1.5) * a;
      if (rand() < 0.02 + 0.06 * s.act[c]) v += (rand() < 0.5 ? -1 : 1) * 1.6 * a;
      s.data[c * s.samples + s.head] = v;
    }
    s.head = ((s.head + 1) % s.samples) | 0;
  }
}

// These numeric RGB stops are the approved brand gradient, shared by both renderers.
export function channelColor(u: number): [number, number, number] {
  u = Math.max(0, Math.min(1, u));
  const t = u < 0.5 ? u * 2 : (u - 0.5) * 2;
  return u < 0.5
    ? [Math.round(107 + 35 * t), Math.round(165 - 16 * t), Math.round(219 - t)]
    : [Math.round(142 + 35 * t), Math.round(149 - 17 * t), Math.round(218 - t)];
}
