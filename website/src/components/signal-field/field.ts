export type Gesture = 'Rest' | 'Fist' | 'Pinch' | 'Index';
export const GESTURES: readonly Gesture[] = ['Rest', 'Fist', 'Pinch', 'Index'];
export const CONFIDENCE: Record<Gesture, number> = { Rest: 0.97, Fist: 0.94, Pinch: 0.91, Index: 0.88 };

// Derived RMS maps from 8-channel forearm bracelet recordings, divided by
// maximum Fist RMS. Index denotes index flexion. No recording samples.
const RMS: Record<Gesture, readonly number[]> = {
  Rest: [0.0166, 0.0247, 0.0258, 0.0187, 0.0237, 0.0444, 0.0259, 0.0229],
  Fist: [0.6122, 1.0000, 0.7758, 0.3918, 0.6676, 0.5276, 0.3552, 0.6188],
  Pinch: [0.0851, 0.1671, 0.7326, 0.4169, 0.5279, 0.4671, 0.1561, 0.0877],
  Index: [0.2221, 0.1321, 0.4732, 0.3591, 0.1783, 0.1133, 0.0770, 0.0653],
};
// [circular electrode correlation, displayed lag-1, broad-innovation probability,
// broad-innovation scale]. Rounded aggregate fit at 120 columns/s.
const TEXTURE: Record<Gesture, readonly number[]> = {
  Rest: [0.106, -0.150, 0.02, 1.6],
  Fist: [0.404, -0.152, 0.08, 2.3],
  Pinch: [0.352, -0.217, 0.08, 2.2],
  Index: [0.367, -0.125, 0.08, 2.3],
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
  rest: Float32Array;
  noise: Float32Array;
  texture: Float32Array;
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
    rest: new Float32Array(channels),
    noise: new Float32Array(8),
    texture: new Float32Array(8),
  };
  const patterns: Record<Gesture, Float32Array> = {
    Rest: new Float32Array(channels), Fist: new Float32Array(channels),
    Pinch: new Float32Array(channels), Index: new Float32Array(channels),
  };
  for (const gesture of GESTURES) fillPattern(patterns[gesture], channels, gesture);
  state.rest.set(patterns.Rest);
  state.act.set(patterns.Rest);
  state.target.set(patterns.Rest);
  setTexture(state, 'Rest');
  patternCache.set(state, patterns);
  return state;
}

function fillPattern(target: Float32Array, channels: number, gesture: Gesture): void {
  const map = RMS[gesture];
  for (let c = 0; c < channels; c++) {
    const position = c * 8 / channels;
    const lo = Math.floor(position), mix = position - lo;
    target[c] = map[lo] * (1 - mix) + map[(lo + 1) % 8] * mix;
  }
}

function setTexture(s: FieldState, gesture: Gesture): void {
  const t = TEXTURE[gesture], out = s.texture;
  out[0] = t[0];
  out[1] = Math.sqrt(t[0]);
  out[2] = Math.sqrt(1 - t[0]);
  out[3] = t[1];
  out[4] = Math.sqrt(1 - t[1] * t[1]);
  out[5] = t[2];
  out[6] = t[3];
  out[7] = 1 / Math.sqrt(1 + t[2] * (t[3] * t[3] - 1));
}

export function setGesture(s: FieldState, gesture: Gesture): void {
  const cached = patternCache.get(s);
  if (cached) s.target.set(cached[gesture]);
  else fillPattern(s.target, s.channels, gesture);
  setTexture(s, gesture);
  s.gesture = gesture;
}

/** Trace height in channel lanes per unit of signal: bulk activity stays inside its lane. */
export const FIELD_GAIN = 0.26;
/** A trace brightens toward FIELD_HOT as its swing grows from HEAT_LOW to HEAT_HIGH lanes. */
export const HEAT_LOW = 0.08;
export const HEAT_HIGH = 0.5;
export const FIELD_HOT: [number, number, number] = [255, 232, 248];

// 120 columns/s, point sampling. Single-gesture takes lack transition cues,
// so retain the 18 ms envelope constants. All mutable noise lives in buffers.
export const ONSET_TAU = 0.018;
export const OFFSET_TAU = 0.018;
const ATTACK = 1 - Math.exp(-1 / (120 * ONSET_TAU));
const RELEASE = 1 - Math.exp(-1 / (120 * OFFSET_TAU));

// Six uniforms approximate a unit Gaussian without transcendental hot-path work.
function normal(rand: () => number): number {
  return (rand() + rand() + rand() + rand() + rand() + rand() - 3) * 1.41421356;
}

// Eight correlated carriers are interpolated on the same closed bracelet as the
// RMS maps. Variance normalization keeps each lane's RMS equal to its map.
// Hot path: no views, objects, closures, or per-column allocation.
export function stepField(s: FieldState, k: number, rand: () => number): void {
  const t = s.texture;
  for (let i = 0; i < k; i++) {
    const scale = (rand() < t[5] ? t[6] : 1) * t[7];
    const common = normal(rand) * t[1];
    for (let e = 0; e < 8; e++) {
      s.noise[e] = s.noise[e] * t[3] + (common + normal(rand) * t[2]) * scale * t[4];
    }
    for (let c = 0; c < s.channels; c++) {
      s.act[c] += (s.target[c] - s.act[c]) * (s.target[c] > s.act[c] ? ATTACK : RELEASE);
      const position = c * 8 / s.channels;
      const lo = Math.floor(position), mix = position - lo;
      const noise = s.noise[lo] * (1 - mix) + s.noise[(lo + 1) % 8] * mix;
      const variance = (1 - mix) * (1 - mix) + mix * mix + 2 * t[0] * mix * (1 - mix);
      s.data[c * s.samples + s.head] = noise * s.act[c] / Math.sqrt(variance);
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
