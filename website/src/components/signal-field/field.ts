export type Gesture = 'Rest' | 'Fist' | 'Open' | 'Pinch';
export const GESTURES: readonly Gesture[] = ['Rest', 'Fist', 'Open', 'Pinch'];
export const CONFIDENCE: Record<Gesture, number> = { Rest: 0.97, Fist: 0.94, Open: 0.91, Pinch: 0.88 };

// Rounded per-channel RMS / maximum Fist RMS from the local 320-channel take.
// Highest-energy contiguous block: channels 45--108 (zero based). No samples.
const REST_RMS = [
  0.136, 0.088, 0.123, 0.092, 0.108, 0.106, 0.093, 0.121,
  0.09, 0.119, 0.091, 0.113, 0.096, 0.102, 0.11, 0.099,
  0.115, 0.097, 0.11, 0.09, 0.083, 0.098, 0.078, 0.106,
  0.083, 0.102, 0.09, 0.087, 0.093, 0.079, 0.103, 0.083,
  0.104, 0.088, 0.092, 0.095, 0.081, 0.099, 0.081, 0.102,
  0.087, 0.096, 0.094, 0.086, 0.098, 0.083, 0.1, 0.086,
  0.097, 0.092, 0.091, 0.097, 0.083, 0.097, 0.085, 0.097,
  0.092, 0.094, 0.097, 0.088, 0.094, 0.085, 0.095, 0.089,
];
const FIST_RMS = [
  1.0, 0.8, 0.79, 0.776, 0.796, 0.786, 0.786, 0.785,
  0.789, 0.788, 0.785, 0.79, 0.786, 0.789, 0.788, 0.786,
  0.787, 0.785, 0.789, 0.786, 0.788, 0.789, 0.79, 0.788,
  0.784, 0.786, 0.79, 0.789, 0.787, 0.789, 0.789, 0.787,
  0.785, 0.789, 0.788, 0.788, 0.788, 0.787, 0.787, 0.787,
  0.789, 0.788, 0.788, 0.788, 0.786, 0.787, 0.788, 0.791,
  0.789, 0.786, 0.787, 0.788, 0.79, 0.788, 0.789, 0.787,
  0.788, 0.787, 0.785, 0.788, 0.785, 0.786, 0.787, 0.787,
];
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
  phase: Float32Array;
  pulse: Float32Array;
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
    phase: new Float32Array(channels),
    pulse: new Float32Array(2),
  };
  const patterns: Record<Gesture, Float32Array> = {
    Rest: new Float32Array(channels), Fist: new Float32Array(channels),
    Open: new Float32Array(channels), Pinch: new Float32Array(channels),
  };
  for (const gesture of GESTURES) fillPattern(patterns[gesture], channels, gesture);
  state.rest.set(patterns.Rest);
  state.act.set(patterns.Rest);
  state.target.set(patterns.Rest);
  for (let c = 0; c < channels; c++) state.phase[c] = (c * 0.61803398875) % 1;
  patternCache.set(state, patterns);
  return state;
}

function fillPattern(target: Float32Array, channels: number, gesture: Gesture): void {
  for (let c = 0; c < channels; c++) {
    const u = c / Math.max(1, channels - 1);
    const position = u * 63;
    const lo = Math.floor(position), hi = Math.min(63, lo + 1), mix = position - lo;
    const map = gesture === 'Rest' ? REST_RMS : FIST_RMS;
    let rms = map[lo] * (1 - mix) + map[hi] * mix;
    // Open/Pinch remain synthetic; gentle spatial envelopes on the same map.
    if (gesture === 'Open' || gesture === 'Pinch') {
      const centre = gesture === 'Open' ? 0.68 : 0.25;
      rms *= 0.22 + 0.78 * Math.exp(-0.5 * ((u - centre) / 0.27) ** 2);
    }
    target[c] = rms;
  }
}

export function setGesture(s: FieldState, gesture: Gesture): void {
  const cached = patternCache.get(s);
  if (cached) s.target.set(cached[gesture]);
  else fillPattern(s.target, s.channels, gesture);
  s.gesture = gesture;
}

/** Trace height in channel lanes per unit of signal: bulk activity stays inside its lane. */
export const FIELD_GAIN = 0.26;

// 120 columns/s, point sampling. Envelope taus are measured from 50 ms RMS
// 10--90% widths, excluding cue offset. All mutable noise lives in buffers.
export const ONSET_TAU = 0.018;
export const OFFSET_TAU = 0.018;
const ATTACK = 1 - Math.exp(-1 / (120 * ONSET_TAU));
const RELEASE = 1 - Math.exp(-1 / (120 * OFFSET_TAU));

// Hot path: no views, objects, closures, or per-column allocation.
export function stepField(s: FieldState, k: number, rand: () => number): void {
  for (let i = 0; i < k; i++) {
    let spike = s.pulse[0];
    s.pulse[0] = s.pulse[1];
    s.pulse[1] = 0;
    // Sparse biphasic low-effort potentials, shared with alternating polarity.
    if (rand() < 0.0017) {
      const sign = rand() < 0.5 ? -1 : 1;
      spike += sign * 15;
      s.pulse[0] -= sign * 5;
      s.pulse[1] += sign * 1;
    }
    let previous = 0;
    for (let c = 0; c < s.channels; c++) {
      s.act[c] += (s.target[c] - s.act[c]) * (s.target[c] > s.act[c] ? ATTACK : RELEASE);
      const effort = Math.max(0, Math.min(1, (s.act[c] - s.rest[c]) / Math.max(0.1, 0.79 - s.rest[c])));
      // Reflected jitter preserves a uniform marginal while giving the sampled
      // active texture its measured negative lag-1 correlation (~ -0.31).
      let phase = 1 - s.phase[c] + (rand() - 0.5) * 0.564;
      phase -= Math.floor(phase);
      s.phase[c] = phase;
      const r = 0.18 - 0.02 * effort;
      const noise = (phase * 2 - 1) * 1.7320508 * Math.sqrt(1 - r * r) + previous * r;
      previous = noise;
      const v = noise * (0.84 + 0.16 * effort) + spike * (c % 2 ? -1 : 1) * (1 - effort);
      s.data[c * s.samples + s.head] = v * s.act[c];
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
